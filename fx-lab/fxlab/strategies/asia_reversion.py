"""Mean reversion v klidnych hodinach.

MYSLENKA
--------
V asijske session je na EUR/USD malo objemu a zadny smerovy zajem. Vychylky
od prumeru jsou casteji sum nez zacatek trendu, takze se casto vraci zpet.
Obchoduje se PROTI vychylce.

REALITA
-------
Mean reversion ma vysokou uspesnost a male zisky na obchod. To je psychologicky
prijemne a matematicky nebezpecne - jedna velka ztrata smaze dvacet malych
zisku. Klicove je proto:
  - tvrdy stop (zadne "ono se to vrati")
  - vyhnout se zpravam (v asijske session hlavne BOJ, RBA, cinska data)

Kdyz uvidis uspesnost 80 % a profit factor 1.05, je to presne tenhle profil.
Neni to hrana, je to jen prehazene rozlozeni.
"""

from __future__ import annotations

import pandas as pd

from ..engine import Close, Context, Order
from .base import Strategy, atr, rsi


class AsiaReversion(Strategy):
    def __init__(
        self,
        start_hour: int = 0,
        end_hour: int = 7,
        lookback: int = 20,
        entry_atr_mult: float = 1.5,
        stop_atr_mult: float = 1.5,
        target_atr_mult: float = 1.0,
        rsi_period: int = 14,
        rsi_long_below: float = 30.0,
        rsi_short_above: float = 70.0,
        max_bars: int = 8,
        atr_period: int = 24,
    ):
        self.params = dict(
            start_hour=start_hour, end_hour=end_hour, lookback=lookback,
            entry_atr_mult=entry_atr_mult, stop_atr_mult=stop_atr_mult,
            target_atr_mult=target_atr_mult, rsi_period=rsi_period,
            rsi_long_below=rsi_long_below, rsi_short_above=rsi_short_above,
            max_bars=max_bars, atr_period=atr_period,
        )
        self.__dict__.update(self.params)
        self.warmup = max(lookback, atr_period, rsi_period) + 5

    def on_bar(self, ctx: Context) -> Order | Close | None:
        hour = ctx.now.hour

        if ctx.position is not None:
            # Po konci klidnych hodin uz nedrzime - prichazi Londyn a objem.
            if hour >= self.end_hour:
                return Close("session_end")
            return None

        if not (self.start_hour <= hour < self.end_hour):
            return None

        bars = ctx.bars
        a = atr(bars, self.atr_period)
        if not (a > 0):
            return None

        mean = float(bars["close"].iloc[-self.lookback:].mean())
        close = float(bars["close"].iloc[-1])
        deviation = close - mean
        r = rsi(bars["close"], self.rsi_period)

        stop_dist = self.stop_atr_mult * a
        target_dist = self.target_atr_mult * a

        # Cena je vyrazne pod prumerem a zaroven prepodana -> long.
        if deviation < -self.entry_atr_mult * a and r < self.rsi_long_below:
            return Order(
                side="long",
                stop_loss=close - stop_dist,
                take_profit=close + target_dist,
                max_bars=self.max_bars,
                tag="asia_long",
            )

        if deviation > self.entry_atr_mult * a and r > self.rsi_short_above:
            return Order(
                side="short",
                stop_loss=close + stop_dist,
                take_profit=close - target_dist,
                max_bars=self.max_bars,
                tag="asia_short",
            )

        return None
