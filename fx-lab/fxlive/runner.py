"""Ziva smycka bota.

ZASADNI VLASTNOST
-----------------
Pouziva PRESNE TY SAME objekty strategii jako backtest - `fxlab.strategies`.
Neni tu druha implementace logiky, kterou by bylo mozne rozladit.
Co jsi otestoval, to bezi.

ZAROVNANI S BACKTESTEM
----------------------
Backtest: strategie vidi bar `i`, prikaz se plni na `open[i+1]`.
Ziva verze: bar `i` se prave uzavrel, strategie ho vidi, market prikaz
odchazi hned - tedy na zacatku baru `i+1`. Stejny okamzik.

Proto se NIKDY nepracuje s nedokoncenou svicky. To by byl look-ahead
v zive podobe: rozhodujes se podle ceny, ktera se jeste zmeni.

CO DELA PRI STARTU
------------------
1. Nacte ulozeny stav.
2. Zepta se BROKERA na skutecne pozice - ulozeny stav se neveri.
3. Kdyz visi nevyrizeny prikaz, dohleda, jestli prosel.
4. Teprve pak zacne obchodovat.
"""

from __future__ import annotations

import datetime as dt
import logging
import signal
import time
import uuid
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from fxlab.engine import Close, Context, Order, Position

from .broker import Broker, BrokerError, BrokerPosition, TransientError
from .risk import Rejected, RiskManager
from .state import BotState, Journal, StateStore

log = logging.getLogger(__name__)

GRANULARITY_SECONDS = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
    "H1": 3600, "H4": 14400, "D": 86400,
}


@dataclass
class RunnerConfig:
    instrument: str = "EUR_USD"
    granularity: str = "H1"
    history_bars: int = 300
    poll_buffer_seconds: int = 20
    """Cekani po uzavreni svicky, nez se o ni rekne. Broker ji musi stihnout."""

    max_consecutive_errors: int = 10
    dry_run: bool = True
    pip: float = 0.0001


class Runner:
    def __init__(
        self,
        config: RunnerConfig,
        broker: Broker,
        strategy,
        risk: RiskManager,
        store: StateStore,
        journal: Journal,
        data_broker: Optional[Broker] = None,
    ):
        self.cfg = config
        self.broker = broker
        self.strategy = strategy
        self.risk = risk
        self.store = store
        self.journal = journal
        # Pri dry-runu jde obchodovat na papire, ale data brat ze zive OANDA.
        self.data_broker = data_broker or broker

        self.state: BotState = store.load()
        self.risk.state = self.state.risk
        self._stop = False
        self._errors = 0

    # ------------------------------------------------------------------
    # zivotni cyklus
    # ------------------------------------------------------------------

    def install_signal_handlers(self) -> None:
        def handler(signum, frame):
            log.warning("Signal %s - koncim po dokonceni cyklu.", signum)
            self._stop = True

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

    def reconcile(self) -> Optional[BrokerPosition]:
        """Sladi ulozeny stav se skutecnosti u brokera.

        Tohle je nejdulezitejsi funkce celeho bota. Bez ni se po restartu
        muzes dostat do stavu, kdy bot "nevi" o otevrene pozici a otevre
        druhou.

        Zdroj pravdy je VZDY broker.
        """
        pos = self.broker.position(self.cfg.instrument)
        acct = self.broker.account()

        log.info(
            "Reconcile: ucet %s %.2f (equity %.2f), pozice u brokera: %s",
            acct.currency, acct.balance, acct.equity,
            f"{pos.side} {pos.units:.0f} @ {pos.entry_price}" if pos else "zadna",
        )

        if self.state.pending_client_id:
            if pos is not None:
                log.warning(
                    "Nevyrizeny prikaz %s: pozice EXISTUJE - prikaz prosel.",
                    self.state.pending_client_id,
                )
            else:
                log.warning(
                    "Nevyrizeny prikaz %s: pozice neexistuje - prikaz neprosel.",
                    self.state.pending_client_id,
                )
            self.journal.write(
                "reconcile_pending", self._now_iso(),
                client_id=self.state.pending_client_id,
                detail={"position_found": pos is not None},
            )
            self.state.pending_client_id = ""

        if pos is not None and not self.state.open_trade_id:
            log.warning(
                "Pozice u brokera, o ktere bot nevedel (trade %s). Prebiram ji. "
                "Vynucene zavreni po N barech na ni nepujde uplatnit - "
                "nevim, kolik baru uz bezi. Hlida ji stop-loss u brokera.",
                pos.trade_id,
            )
            self.state.open_bars_held = 0
            self.state.open_max_bars = 0

        if pos is None and self.state.open_trade_id:
            log.warning(
                "Bot cekal pozici %s, ale u brokera zadna neni. "
                "Zavrela se stopem nebo rucne.", self.state.open_trade_id,
            )
            self.state.open_bars_held = 0
            self.state.open_max_bars = 0

        self.state.open_trade_id = pos.trade_id if pos else ""
        self.risk.roll_day(self._now(), acct.equity)
        self.risk.update_equity(acct.equity)
        self.state.risk = self.risk.state
        self.store.save(self.state)

        self.journal.write(
            "start", self._now_iso(), instrument=self.cfg.instrument,
            equity=acct.equity, detail={
                "strategy": type(self.strategy).__name__,
                "params": getattr(self.strategy, "params", {}),
                "dry_run": self.cfg.dry_run,
                "position": bool(pos),
                "halted": self.risk.state.halted,
            },
        )
        return pos

    def run_forever(self) -> None:
        self.install_signal_handlers()
        self.reconcile()

        if self.risk.state.halted:
            log.error(
                "Bot je v HALTU: %s. Spust s --resume, az zjistis proc.",
                self.risk.state.halt_reason,
            )
            return

        log.info(
            "Bot bezi. %s %s, strategie %s, %s",
            self.cfg.instrument, self.cfg.granularity,
            type(self.strategy).__name__,
            "DRY-RUN (zadne skutecne prikazy)" if self.cfg.dry_run else "ZIVE",
        )

        while not self._stop:
            try:
                self.step()
                self._errors = 0
            except TransientError as e:
                self._errors += 1
                log.warning("Docasna chyba (%s/%s): %s",
                            self._errors, self.cfg.max_consecutive_errors, e)
                if self._errors >= self.cfg.max_consecutive_errors:
                    log.error("Prilis mnoho chyb za sebou, koncim.")
                    self.journal.write("fatal", self._now_iso(), detail=str(e))
                    break
            except BrokerError as e:
                log.error("Chyba brokera: %s", e)
                self.journal.write("broker_error", self._now_iso(), detail=str(e))
                break
            except Exception as e:  # noqa: BLE001
                log.exception("Neocekavana chyba - koncim pro jistotu.")
                self.journal.write("fatal", self._now_iso(), detail=repr(e))
                break

            if self.risk.state.halted:
                log.error("HALT: %s. Koncim.", self.risk.state.halt_reason)
                break

            if not self._stop:
                self._sleep_until_next_bar()

        self.store.save(self.state)
        self.journal.write("stop", self._now_iso(),
                           detail={"halted": self.risk.state.halted})
        log.info("Bot ukoncen.")

    # ------------------------------------------------------------------
    # jeden cyklus
    # ------------------------------------------------------------------

    def step(self) -> None:
        bars = self.data_broker.candles(
            self.cfg.instrument, self.cfg.granularity, self.cfg.history_bars
        )
        if bars.empty:
            raise TransientError("zadna data")

        last_time = bars.index[-1]
        last_key = last_time.isoformat()

        # Stejnou svicku nikdy nezpracovavame dvakrat.
        if last_key == self.state.last_bar_time:
            return

        # Simulovany broker si SL/TP nehlida sam - skutecny ano. Kontrola
        # musi probehnout PRED tim, nez bar uvidi strategie: pozice otevrena
        # behem tohohle baru vznikne az na jeho zaveru, takze ji nesmi
        # vykopnout pohyb, ktery probehl driv. Pro OandaBroker je to no-op.
        self._simulate_stops(bars.iloc[-1])

        acct = self.broker.account()
        now = self._now()

        self.risk.roll_day(now, acct.equity)
        self.risk.update_equity(acct.equity)

        halt = self.risk.check_halt(acct.equity)
        if halt:
            self.journal.write("halt", self._now_iso(), equity=acct.equity, detail=halt)
            self._persist(last_key)
            return

        broker_pos = self.broker.position(self.cfg.instrument)
        self._detect_closure(broker_pos, acct)

        if broker_pos is not None:
            self.state.open_bars_held += 1

        ctx = Context(
            bars=bars,
            position=self._to_engine_position(broker_pos),
            equity=acct.equity,
        )

        decision = self.strategy.on_bar(ctx)

        # Vynucene zavreni po N barech ma prednost pred rozhodnutim strategie.
        # Engine backtestu to resi ve sve smycce; tady to musi udelat runner,
        # jinak by se strategie s `max_bars` chovala zive jinak.
        if (
            broker_pos is not None
            and self.state.open_max_bars > 0
            and self.state.open_bars_held >= self.state.open_max_bars
        ):
            decision = Close("max_bars")

        self.journal.write(
            "bar", last_key, instrument=self.cfg.instrument,
            price=float(bars["close"].iloc[-1]), equity=acct.equity,
            detail={
                "decision": type(decision).__name__ if decision else "None",
                "position": broker_pos.side if broker_pos else None,
                "bars_held": self.state.open_bars_held if broker_pos else 0,
            },
        )

        if isinstance(decision, Close) and broker_pos is not None:
            self._do_close(decision.reason, acct)
        elif isinstance(decision, Order) and broker_pos is None:
            self._do_open(decision, bars, acct, now)
        elif isinstance(decision, Order) and broker_pos is not None:
            log.debug("Signal na vstup ignorovan - pozice uz je otevrena.")

        self._persist(last_key)

    # ------------------------------------------------------------------
    # akce
    # ------------------------------------------------------------------

    def _do_open(self, order: Order, bars: pd.DataFrame, acct, now: dt.datetime) -> None:
        blocked = self.risk.can_open(now, acct.equity)
        if blocked:
            log.info("Vstup zablokovan: %s", blocked)
            self.journal.write("blocked", self._now_iso(),
                               instrument=self.cfg.instrument, detail=blocked)
            return

        # Odhad vstupni ceny. Skutecna vyjde z plneni.
        entry = float(bars["close"].iloc[-1])

        try:
            self.risk.validate_order(
                order.side, entry, order.stop_loss, order.take_profit
            )
            units = self.risk.size_position(acct.equity, entry, order.stop_loss)
        except Rejected as e:
            log.warning("Prikaz zamitnut rizikovou vrstvou: %s", e)
            self.journal.write("rejected", self._now_iso(),
                               instrument=self.cfg.instrument, side=order.side,
                               stop_loss=order.stop_loss, detail=str(e))
            return

        client_id = f"fxlive-{uuid.uuid4().hex[:20]}"

        if self.cfg.dry_run:
            log.info(
                "[DRY-RUN] %s %.0f %s @ ~%.5f  SL %.5f  TP %s",
                order.side.upper(), units, self.cfg.instrument, entry,
                order.stop_loss,
                f"{order.take_profit:.5f}" if order.take_profit else "-",
            )
            self.journal.write(
                "dry_open", self._now_iso(), instrument=self.cfg.instrument,
                side=order.side, units=units, price=entry,
                stop_loss=order.stop_loss, take_profit=order.take_profit,
                client_id=client_id, equity=acct.equity, detail=order.tag,
            )
            return

        # Zapsat PRED odeslanim. Kdyz proces spadne, reconcile to dohleda.
        self.state.pending_client_id = client_id
        self.store.save(self.state)

        result = self.broker.market_order(
            self.cfg.instrument, order.side, units,
            order.stop_loss, order.take_profit, client_id,
        )

        self.state.pending_client_id = ""

        if not result.accepted:
            log.warning("Prikaz neprijat: %s", result.reason)
            self.journal.write("order_failed", self._now_iso(),
                               instrument=self.cfg.instrument, side=order.side,
                               units=units, client_id=client_id,
                               detail=result.reason)
            return

        self.state.open_trade_id = result.trade_id or ""
        self.state.open_bars_held = 0
        self.state.open_max_bars = int(order.max_bars or 0)
        self.risk.record_fill(opened=True)
        log.info(
            "OTEVRENO %s %.0f %s @ %.5f (trade %s)",
            order.side.upper(), result.units, self.cfg.instrument,
            result.fill_price, result.trade_id,
        )
        self.journal.write(
            "open", self._now_iso(), instrument=self.cfg.instrument,
            side=order.side, units=result.units, price=result.fill_price,
            stop_loss=order.stop_loss, take_profit=order.take_profit,
            trade_id=result.trade_id, client_id=client_id, equity=acct.equity,
            detail=order.tag,
        )

    def _do_close(self, reason: str, acct) -> None:
        client_id = f"fxlive-close-{uuid.uuid4().hex[:16]}"

        if self.cfg.dry_run:
            log.info("[DRY-RUN] ZAVRIT %s (%s)", self.cfg.instrument, reason)
            self.journal.write("dry_close", self._now_iso(),
                               instrument=self.cfg.instrument,
                               client_id=client_id, detail=reason)
            return

        self.state.pending_client_id = client_id
        self.store.save(self.state)

        result = self.broker.close_position(self.cfg.instrument, client_id)
        self.state.pending_client_id = ""

        if not result.accepted:
            log.warning("Zavreni neproslo: %s", result.reason)
            self.journal.write("close_failed", self._now_iso(),
                               instrument=self.cfg.instrument,
                               client_id=client_id, detail=result.reason)
            return

        self.state.open_trade_id = ""
        self.state.open_bars_held = 0
        self.state.open_max_bars = 0
        log.info("ZAVRENO %s @ %.5f (%s)",
                 self.cfg.instrument, result.fill_price, reason)
        self.journal.write(
            "close", self._now_iso(), instrument=self.cfg.instrument,
            units=result.units, price=result.fill_price,
            trade_id=result.trade_id, client_id=client_id,
            equity=acct.equity, detail=reason,
        )

    def _simulate_stops(self, bar) -> None:
        """U simulovaneho brokera zkontroluje SL/TP na danem baru.

        Skutecny broker drzi stop-loss a take-profit na sve strane a spusti
        je sam. `PaperBroker` ne - bez tohohle by v `--paper` rezimu pozice
        nikdy netrefila stop a drzela se donekonecna.

        Duck-typed: broker, ktery `trigger_stops` nema (OandaBroker), se
        preskoci.
        """
        trigger = getattr(self.broker, "trigger_stops", None)
        if trigger is None:
            return
        reason = trigger(self.cfg.instrument, float(bar["high"]), float(bar["low"]))
        if reason:
            log.info("Simulovany %s zasazen na %s", reason, self.cfg.instrument)

    def _detect_closure(self, broker_pos: Optional[BrokerPosition], acct) -> None:
        """Pozice zmizela, aniz bychom ji zavirali - zasah SL/TP."""
        if self.state.open_trade_id and broker_pos is None:
            log.info("Pozice %s se zavrela sama (stop nebo target).",
                     self.state.open_trade_id)
            self.journal.write(
                "closed_by_broker", self._now_iso(),
                instrument=self.cfg.instrument,
                trade_id=self.state.open_trade_id, equity=acct.equity,
                detail={"bars_held": self.state.open_bars_held},
            )
            self.state.open_trade_id = ""
            self.state.open_bars_held = 0
            self.state.open_max_bars = 0

    # ------------------------------------------------------------------
    # pomocne
    # ------------------------------------------------------------------

    def _to_engine_position(self, bp: Optional[BrokerPosition]) -> Optional[Position]:
        """Prevod pozice brokera na typ, ktery zna strategie.

        Diky tomu strategie nepozna rozdil mezi backtestem a zivym behem -
        vcetne `bars_held` a `max_bars`, na ktere se nektere strategie divaji.
        """
        if bp is None:
            return None
        return Position(
            side=bp.side,
            units=bp.units,
            entry_time=(
                pd.Timestamp(bp.open_time) if bp.open_time
                else pd.Timestamp.now("UTC")
            ),
            entry_price=bp.entry_price,
            stop_loss=bp.stop_loss if bp.stop_loss is not None else 0.0,
            take_profit=bp.take_profit,
            max_bars=self.state.open_max_bars or None,
            bars_held=self.state.open_bars_held,
        )

    def _persist(self, last_bar_key: str) -> None:
        self.state.last_bar_time = last_bar_key
        self.state.risk = self.risk.state
        self.state.strategy_name = type(self.strategy).__name__
        self.store.save(self.state)

    def _sleep_until_next_bar(self) -> None:
        period = GRANULARITY_SECONDS.get(self.cfg.granularity, 3600)
        now = time.time()
        next_close = (int(now) // period + 1) * period
        wait = max(5.0, next_close - now + self.cfg.poll_buffer_seconds)
        log.debug("Cekam %.0f s na dalsi svicku.", wait)

        # Spanek po kouscich, aby signal zabral rychle.
        end = time.time() + wait
        while time.time() < end and not self._stop:
            time.sleep(min(2.0, end - time.time()))

    @staticmethod
    def _now() -> dt.datetime:
        return dt.datetime.now(dt.timezone.utc)

    @classmethod
    def _now_iso(cls) -> str:
        return cls._now().isoformat()
