"""Rizikova vrstva - posledni instance pred odeslanim prikazu.

Strategie navrhuje. Tahle vrstva ma pravo veta.

Oddeleni je zamerne. Strategii budes casto menit a ladit; tyhle limity ne.
Kdyz udelas chybu v logice strategie, tahle vrstva ti omezi skodu.

Kontroly se provadi VZDY, i kdyz jsi si jisty, ze nemuzou nastat.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)


class Rejected(Exception):
    """Prikaz zamitnut rizikovou vrstvou."""


@dataclass
class RiskLimits:
    risk_per_trade: float = 0.005
    """Podil equity riskovany na jeden obchod. 0.005 = 0.5 %."""

    max_daily_loss: float = 0.02
    """Denni ztrata, po ktere se bot vypne. 0.02 = 2 % pocatecni denni equity."""

    max_total_drawdown: float = 0.15
    """Celkovy propad od nejvyssi equity, po kterem se bot vypne natrvalo."""

    max_leverage: float = 30.0
    """ESMA retail limit pro hlavni pary je 30."""

    max_trades_per_day: int = 10
    """Pojistka proti smycce, ktera zacne posilat prikazy v kazdem cyklu."""

    max_position_units: float = 100_000.0
    """Absolutni strop, bez ohledu na vypocet. Pojistka proti chybe v sizingu."""

    min_position_units: float = 1.0

    trading_hours_utc: tuple[int, int] = (0, 24)
    """Okno, ve kterem smi bot otevirat pozice. Zavirat smi kdykoli."""

    trade_on_weekend: bool = False
    """FX je zavreny pa 21:00 - ne 21:00 UTC. Nechavej False."""

    min_stop_distance_pips: float = 3.0
    """Prilis tesny stop = obri pozice a jisty vykop na sumu."""

    max_stop_distance_pips: float = 200.0
    """Prilis siroky stop = pozice tak mala, ze nema smysl."""


@dataclass
class RiskState:
    """Stav, ktery se musi prezit restart bota."""

    day: str = ""
    day_start_equity: float = 0.0
    trades_today: int = 0
    realised_today: float = 0.0
    peak_equity: float = 0.0
    halted: bool = False
    halt_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "day": self.day,
            "day_start_equity": self.day_start_equity,
            "trades_today": self.trades_today,
            "realised_today": self.realised_today,
            "peak_equity": self.peak_equity,
            "halted": self.halted,
            "halt_reason": self.halt_reason,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RiskState":
        return cls(**{k: d[k] for k in d if k in cls.__dataclass_fields__})


class RiskManager:
    def __init__(self, limits: RiskLimits, state: Optional[RiskState] = None,
                 pip: float = 0.0001):
        self.limits = limits
        self.state = state or RiskState()
        self.pip = pip

    # -- denni cyklus -----------------------------------------------------

    def roll_day(self, now: dt.datetime, equity: float) -> bool:
        """Zacatek noveho obchodniho dne. Vraci True, kdyz se den zmenil.

        Denni limit ztraty se pocita od equity na zacatku dne, ne od vkladu.
        Jinak by ti po ziskovem tydnu limit povolil mnohem vetsi ztratu.
        """
        today = now.strftime("%Y-%m-%d")
        if self.state.day == today:
            return False

        self.state.day = today
        self.state.day_start_equity = equity
        self.state.trades_today = 0
        self.state.realised_today = 0.0
        if equity > self.state.peak_equity:
            self.state.peak_equity = equity

        # Denni halt se rusi novym dnem. Celkovy drawdown NE.
        if self.state.halted and self.state.halt_reason.startswith("denni"):
            log.info("Novy den, ruším denní halt (%s)", self.state.halt_reason)
            self.state.halted = False
            self.state.halt_reason = ""
        return True

    def record_fill(self, realised_pnl: float = 0.0, opened: bool = False) -> None:
        if opened:
            self.state.trades_today += 1
        self.state.realised_today += realised_pnl

    def update_equity(self, equity: float) -> None:
        if equity > self.state.peak_equity:
            self.state.peak_equity = equity

    # -- vypinaci podminky ------------------------------------------------

    def check_halt(self, equity: float) -> Optional[str]:
        """Vraci duvod k vypnuti, nebo None. Volat v KAZDEM cyklu."""
        if self.state.halted:
            return self.state.halt_reason

        lim = self.limits

        if self.state.day_start_equity > 0:
            loss = (self.state.day_start_equity - equity) / self.state.day_start_equity
            if loss >= lim.max_daily_loss:
                reason = (
                    f"denni ztrata {loss:.2%} dosahla limitu {lim.max_daily_loss:.2%}"
                )
                self._halt(reason)
                return reason

        if self.state.peak_equity > 0:
            dd = (self.state.peak_equity - equity) / self.state.peak_equity
            if dd >= lim.max_total_drawdown:
                reason = (
                    f"celkovy drawdown {dd:.2%} dosahl limitu "
                    f"{lim.max_total_drawdown:.2%}"
                )
                self._halt(reason)
                return reason

        return None

    def _halt(self, reason: str) -> None:
        self.state.halted = True
        self.state.halt_reason = reason
        log.error("HALT: %s", reason)

    def resume(self) -> None:
        """Rucni odblokovani. Zavolej az potom, co jsi zjistil, co se stalo."""
        log.warning("Rucni resume z haltu: %s", self.state.halt_reason)
        self.state.halted = False
        self.state.halt_reason = ""

    # -- povoleni vstupu --------------------------------------------------

    def can_open(self, now: dt.datetime, equity: float) -> Optional[str]:
        """Vraci duvod, PROC nesmi otevrit. None = smi."""
        halt = self.check_halt(equity)
        if halt:
            return f"halt: {halt}"

        lim = self.limits

        if not lim.trade_on_weekend and self._market_closed(now):
            return "trh je zavreny"

        lo, hi = lim.trading_hours_utc
        if not (lo <= now.hour < hi):
            return f"mimo obchodni okno {lo}-{hi} UTC"

        if self.state.trades_today >= lim.max_trades_per_day:
            return (
                f"denni limit obchodu vycerpan "
                f"({self.state.trades_today}/{lim.max_trades_per_day})"
            )

        return None

    @staticmethod
    def _market_closed(now: dt.datetime) -> bool:
        wd, h = now.weekday(), now.hour
        return wd == 5 or (wd == 6 and h < 21) or (wd == 4 and h >= 21)

    # -- velikost pozice --------------------------------------------------

    def size_position(
        self, equity: float, entry_price: float, stop_loss: float,
    ) -> float:
        """Velikost pozice v jednotkach. Vyhodi `Rejected`, kdyz nedava smysl.

        Stejny vypocet jako v backtestu: zasah stopu stoji presne
        `risk_per_trade` z equity.

        POZOR: plati pro pary kotovane v USD (EURUSD, GBPUSD, AUDUSD)
        na USD uctu. U JPY paru a crossu je potreba prepocet kurzem
        kotovane meny - tohle to nedela a zamerne to radeji odmitne.
        """
        lim = self.limits
        stop_distance = abs(entry_price - stop_loss)

        if stop_distance <= 0:
            raise Rejected("stop-loss je na urovni vstupu")

        pips = stop_distance / self.pip
        if pips < lim.min_stop_distance_pips:
            raise Rejected(
                f"stop je prilis tesny ({pips:.1f} pipu, minimum "
                f"{lim.min_stop_distance_pips})"
            )
        if pips > lim.max_stop_distance_pips:
            raise Rejected(
                f"stop je prilis siroky ({pips:.1f} pipu, maximum "
                f"{lim.max_stop_distance_pips})"
            )

        if equity <= 0:
            raise Rejected("nulova nebo zaporna equity")

        units = (equity * lim.risk_per_trade) / stop_distance

        max_by_leverage = equity * lim.max_leverage / entry_price
        units = min(units, max_by_leverage, lim.max_position_units)

        if units < lim.min_position_units:
            raise Rejected(
                f"vypoctena velikost {units:.2f} je pod minimem "
                f"{lim.min_position_units}"
            )

        return float(units)

    def validate_order(
        self, side: str, entry_price: float, stop_loss: float,
        take_profit: Optional[float],
    ) -> None:
        """Kontrola smysluplnosti prikazu. Vyhodi `Rejected`."""
        if side not in ("long", "short"):
            raise Rejected(f"neznama strana: {side}")

        if side == "long":
            if stop_loss >= entry_price:
                raise Rejected("long: stop-loss neni pod vstupem")
            if take_profit is not None and take_profit <= entry_price:
                raise Rejected("long: take-profit neni nad vstupem")
        else:
            if stop_loss <= entry_price:
                raise Rejected("short: stop-loss neni nad vstupem")
            if take_profit is not None and take_profit >= entry_price:
                raise Rejected("short: take-profit neni pod vstupem")

        if entry_price <= 0:
            raise Rejected("nesmyslna vstupni cena")
