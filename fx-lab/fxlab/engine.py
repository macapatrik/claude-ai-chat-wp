"""Bar-by-bar backtest engine bez look-ahead biasu.

KLICOVA VLASTNOST
-----------------
Strategie na baru `i` vidi data jen do `close[i]` vcetne. Jeji prikaz se
vyplni az na `open[i+1]`. Tohle je vynucene strukturou smycky, ne disciplinou
programatora - nejde to obejit ani omylem.

Nejcastejsi chyba v amaterskych backtestech je presne opak: strategie se
rozhodne podle `close[i]` a vyplni se na `close[i]`. To vypada jako drobnost,
ale na intradennich datech to samo o sobe vyrobi "ziskovou" strategii z ciste
nahody.

KONZERVATIVNI PREDPOKLADY
-------------------------
1. Kdyz bar obsahuje soucasne stop-loss i take-profit, predpoklada se, ze
   se trefil STOP. Bez tick dat nejde poznat poradi, a tenhle predpoklad
   drzi vysledky na pesimisticke strane.
2. Kdyz trh otevre za stopem (gap, vikend, zpravy), plni se na OPEN, ne na
   urovni stopu. Realne se tohle deje a pripravi te o vic, nez cekas.
3. OHLC se bere jako mid cena. Spread a slippage se uctuji zvlast jako
   naklad, aby bylo v reportu videt, kolik zerou.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

import numpy as np
import pandas as pd

from .costs import CostModel

Side = Literal["long", "short"]

REQUIRED_COLUMNS = ("open", "high", "low", "close")


# --------------------------------------------------------------------------
# Datove typy
# --------------------------------------------------------------------------


@dataclass
class Order:
    """Pozadavek strategie na otevreni pozice. Vyplni se na dalsim baru."""

    side: Side
    stop_loss: float
    """Absolutni cena stop-lossu. Povinne - bez stopu engine obchod odmitne."""

    take_profit: Optional[float] = None
    max_bars: Optional[int] = None
    """Vynucene zavreni po N barech. None = drzi az do SL/TP."""

    tag: str = ""


class Close:
    """Sentinel: strategie chce zavrit pozici na dalsim otevreni."""

    __slots__ = ("reason",)

    def __init__(self, reason: str = "signal"):
        self.reason = reason


@dataclass
class Position:
    side: Side
    units: float
    entry_time: pd.Timestamp
    entry_price: float
    stop_loss: float
    take_profit: Optional[float]
    max_bars: Optional[int]
    bars_held: int = 0
    swap_accrued: float = 0.0
    tag: str = ""


@dataclass
class Trade:
    side: Side
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    units: float
    gross_pnl: float
    costs: float
    swap: float
    exit_reason: str
    bars_held: int
    risk_amount: float
    """Kolik USD bylo v riziku pri vstupu. Slouzi k prepoctu na R-multiply."""

    tag: str = ""

    @property
    def net_pnl(self) -> float:
        return self.gross_pnl - self.costs - self.swap

    @property
    def r_multiple(self) -> float:
        """Vysledek v nasobcich riskovane castky. Klicova metrika."""
        if self.risk_amount <= 0:
            return 0.0
        return self.net_pnl / self.risk_amount


@dataclass
class Context:
    """To, co vidi strategie. Nic vic neexistuje."""

    bars: pd.DataFrame
    """Historie VCETNE aktualniho baru. Posledni radek = prave uzavreny bar."""

    position: Optional[Position]
    equity: float

    @property
    def now(self) -> pd.Timestamp:
        return self.bars.index[-1]

    @property
    def last(self) -> pd.Series:
        return self.bars.iloc[-1]


@dataclass
class Result:
    trades: list[Trade]
    equity_curve: pd.Series
    initial_equity: float
    costs: CostModel
    rejected_orders: int = 0
    meta: dict = field(default_factory=dict)


# --------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------


class Backtest:
    """Bar-by-bar backtest jedne strategie na jednom instrumentu.

    Parameters
    ----------
    bars
        DataFrame indexovany UTC timestampem, sloupce open/high/low/close.
        Volitelne `spread` (v pipech) pro promenlivy spread.
    strategy
        Objekt s metodou `on_bar(ctx) -> Order | Close | None` a atributem
        `warmup` (kolik baru potrebuje, nez zacne obchodovat).
    risk_per_trade
        Podil equity riskovany na jeden obchod. 0.005 = 0.5 %.
        Velikost pozice se dopocita ze vzdalenosti stop-lossu.
    max_leverage
        Strop na velikost pozice. ESMA retail limit je 30 pro hlavni pary.
    """

    def __init__(
        self,
        bars: pd.DataFrame,
        strategy,
        costs: CostModel,
        initial_equity: float = 10_000.0,
        risk_per_trade: float = 0.005,
        max_leverage: float = 30.0,
        rollover_hour_utc: int = 21,
    ):
        self._validate(bars)
        self.bars = bars
        self.strategy = strategy
        self.costs = costs
        self.initial_equity = float(initial_equity)
        self.risk_per_trade = float(risk_per_trade)
        self.max_leverage = float(max_leverage)
        self.rollover_hour_utc = rollover_hour_utc

    @staticmethod
    def _validate(bars: pd.DataFrame) -> None:
        missing = [c for c in REQUIRED_COLUMNS if c not in bars.columns]
        if missing:
            raise ValueError(f"Chybi sloupce: {missing}")
        if not isinstance(bars.index, pd.DatetimeIndex):
            raise ValueError("Index musi byt DatetimeIndex v UTC.")
        if not bars.index.is_monotonic_increasing:
            raise ValueError("Bary musi byt serazene vzestupne podle casu.")
        if bars.index.has_duplicates:
            raise ValueError("Index obsahuje duplicitni timestampy.")
        bad = bars[(bars.high < bars.low) | (bars.high < bars.open) |
                   (bars.high < bars.close) | (bars.low > bars.open) |
                   (bars.low > bars.close)]
        if len(bad):
            raise ValueError(
                f"Nekonzistentni OHLC na {len(bad)} barech, prvni: {bad.index[0]}"
            )

    # ----------------------------------------------------------------------

    def run(self) -> Result:
        bars = self.bars
        n = len(bars)
        warmup = max(int(getattr(self.strategy, "warmup", 0)), 1)
        if n <= warmup + 2:
            raise ValueError(f"Prilis malo baru ({n}) na warmup {warmup}.")

        opens = bars["open"].to_numpy(float)
        highs = bars["high"].to_numpy(float)
        lows = bars["low"].to_numpy(float)
        closes = bars["close"].to_numpy(float)
        index = bars.index

        equity = self.initial_equity
        position: Optional[Position] = None
        pending: Optional[Order | Close] = None
        trades: list[Trade] = []
        equity_points = np.empty(n, dtype=float)
        equity_points[:] = np.nan
        rejected = 0

        if hasattr(self.strategy, "reset"):
            self.strategy.reset()

        for i in range(warmup, n):
            ts = index[i]

            # --- 1. Vyrizeni prikazu zadaneho na predchozim baru -----------
            if pending is not None:
                if isinstance(pending, Close) and position is not None:
                    trade, equity = self._close_position(
                        position, ts, opens[i], pending.reason, equity
                    )
                    trades.append(trade)
                    position = None
                elif isinstance(pending, Order) and position is None:
                    position = self._open_position(pending, ts, opens[i], equity)
                    if position is None:
                        rejected += 1
                pending = None

            # --- 2. Kontrola SL/TP na aktualnim baru -----------------------
            if position is not None:
                position.bars_held += 1
                exit_price, reason = self._check_exit(
                    position, opens[i], highs[i], lows[i]
                )
                if exit_price is not None:
                    trade, equity = self._close_position(
                        position, ts, exit_price, reason, equity
                    )
                    trades.append(trade)
                    position = None

            # --- 3. Swap za drzeni pres rollover ---------------------------
            if position is not None and i > 0:
                nights = self._rollover_nights(index[i - 1], ts)
                if nights:
                    position.swap_accrued += self.costs.swap_cost(
                        position.units, position.side, nights
                    )

            # --- 4. Zaznam equity (mark-to-market na close) ----------------
            equity_points[i] = self._mark_to_market(position, equity, closes[i])

            # --- 5. Rozhodnuti strategie -----------------------------------
            # Vidi historii do close[i] vcetne. Jeji prikaz se vyplni az
            # na open[i+1]. Look-ahead je tim strukturalne vyloucen.
            if i < n - 1:
                ctx = Context(
                    bars=bars.iloc[: i + 1],
                    position=position,
                    equity=equity_points[i],
                )
                decision = self.strategy.on_bar(ctx)
                if decision is not None:
                    if isinstance(decision, Order) and position is not None:
                        pass  # uz mame pozici, novy vstup se ignoruje
                    else:
                        pending = decision

                # Vynucene zavreni po N barech ma prednost pred strategii.
                if (
                    position is not None
                    and position.max_bars is not None
                    and position.bars_held >= position.max_bars
                ):
                    pending = Close("max_bars")

        # Otevrenou pozici na konci dat zavreme na poslednim close.
        if position is not None:
            trade, equity = self._close_position(
                position, index[-1], closes[-1], "end_of_data", equity
            )
            trades.append(trade)
            equity_points[-1] = equity

        curve = pd.Series(equity_points, index=index, name="equity").ffill()
        curve.iloc[:warmup] = self.initial_equity

        return Result(
            trades=trades,
            equity_curve=curve,
            initial_equity=self.initial_equity,
            costs=self.costs,
            rejected_orders=rejected,
            meta={
                "strategy": type(self.strategy).__name__,
                "params": getattr(self.strategy, "params", {}),
                "bars": n,
                "start": str(index[0]),
                "end": str(index[-1]),
                "risk_per_trade": self.risk_per_trade,
            },
        )

    # ----------------------------------------------------------------------

    def _open_position(
        self, order: Order, ts: pd.Timestamp, price: float, equity: float
    ) -> Optional[Position]:
        stop_distance = abs(price - order.stop_loss)
        if stop_distance <= 0:
            return None

        # Stop musi lezet na spravne strane vstupu.
        if order.side == "long" and order.stop_loss >= price:
            return None
        if order.side == "short" and order.stop_loss <= price:
            return None

        risk_amount = equity * self.risk_per_trade
        units = risk_amount / stop_distance

        max_units = equity * self.max_leverage / price
        units = min(units, max_units)
        if units <= 0:
            return None

        return Position(
            side=order.side,
            units=units,
            entry_time=ts,
            entry_price=price,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            max_bars=order.max_bars,
            tag=order.tag,
        )

    def _check_exit(
        self, pos: Position, o: float, h: float, l: float
    ) -> tuple[Optional[float], str]:
        """Vraci (cena vystupu, duvod) nebo (None, "")."""
        sl, tp = pos.stop_loss, pos.take_profit

        if pos.side == "long":
            # Gap pres stop pri otevreni - plnime na open, ne na stopu.
            if o <= sl:
                return o, "stop_gap"
            if tp is not None and o >= tp:
                return o, "target_gap"
            hit_sl = l <= sl
            hit_tp = tp is not None and h >= tp
        else:
            if o >= sl:
                return o, "stop_gap"
            if tp is not None and o <= tp:
                return o, "target_gap"
            hit_sl = h >= sl
            hit_tp = tp is not None and l <= tp

        # Konzervativne: kdyz bar obsahuje oboji, predpoklada se stop.
        if hit_sl:
            return sl, "stop"
        if hit_tp:
            return tp, "target"
        return None, ""

    def _close_position(
        self, pos: Position, ts: pd.Timestamp, price: float, reason: str, equity: float
    ) -> tuple[Trade, float]:
        direction = 1.0 if pos.side == "long" else -1.0
        gross = direction * (price - pos.entry_price) * pos.units
        cost = self.costs.round_trip_cost(pos.units)
        swap = pos.swap_accrued
        risk_amount = abs(pos.entry_price - pos.stop_loss) * pos.units

        trade = Trade(
            side=pos.side,
            entry_time=pos.entry_time,
            exit_time=ts,
            entry_price=pos.entry_price,
            exit_price=price,
            units=pos.units,
            gross_pnl=gross,
            costs=cost,
            swap=swap,
            exit_reason=reason,
            bars_held=pos.bars_held,
            risk_amount=risk_amount,
            tag=pos.tag,
        )
        return trade, equity + trade.net_pnl

    def _mark_to_market(
        self, pos: Optional[Position], equity: float, price: float
    ) -> float:
        if pos is None:
            return equity
        direction = 1.0 if pos.side == "long" else -1.0
        unrealised = direction * (price - pos.entry_price) * pos.units
        return equity + unrealised - self.costs.round_trip_cost(pos.units) - pos.swap_accrued

    def _rollover_nights(self, prev: pd.Timestamp, now: pd.Timestamp) -> int:
        """Kolik rolloveru (21:00 UTC) padlo mezi dva bary."""
        h = self.rollover_hour_utc
        prev_roll = (prev - pd.Timedelta(hours=h)).floor("D")
        now_roll = (now - pd.Timedelta(hours=h)).floor("D")
        nights = int((now_roll - prev_roll).days)
        if nights <= 0:
            return 0
        # Trojity swap jednou tydne (obvykle ve stredu).
        extra = 2 if now.weekday() == self.costs.triple_swap_weekday else 0
        return nights + extra
