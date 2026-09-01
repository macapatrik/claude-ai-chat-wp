"""Donchian breakout - proraz N-baroveho maxima/minima.

MYSLENKA
--------
Nejjednodussi trend-following, jaky existuje. Kdyz cena prorazi maximum
poslednich N baru, jde se long. Stop podle ATR.

REALITA
-------
Na akciovych indexech a komoditach tohle historicky fungovalo. Na FX
majorech je to slabsi - meny netrenduji tak cistě, protoze centralni banky
aktivne tlumi pohyby.

Ceka te nizka uspesnost (30-40 %) a dlouhe serie ztrat. Vydelava to na malo
velkych obchodech. Kdyz nesnesesh deset ztrat za sebou, tenhle styl neni
pro tebe - a je lepsi to zjistit z backtestu nez z uctu.

Slouzi tu hlavne jako REFERENCE: kazda slozitejsi strategie by mela byt
lepsi nez tahle triviální. Kdyz neni, ta slozitost k nicemu neni.
"""

from __future__ import annotations

import pandas as pd

from ..engine import Close, Context, Order
from .base import Strategy, atr


class DonchianBreakout(Strategy):
    def __init__(
        self,
        channel: int = 48,
        stop_atr_mult: float = 2.0,
        target_r: float = 2.0,
        atr_period: int = 24,
        trade_hours: tuple[int, int] = (7, 20),
        max_bars: int = 48,
        allow_short: bool = True,
    ):
        self.params = dict(
            channel=channel, stop_atr_mult=stop_atr_mult, target_r=target_r,
            atr_period=atr_period, trade_hours=trade_hours, max_bars=max_bars,
            allow_short=allow_short,
        )
        self.__dict__.update(self.params)
        self.warmup = max(channel, atr_period) + 5

    def on_bar(self, ctx: Context) -> Order | Close | None:
        if ctx.position is not None:
            return None

        lo_h, hi_h = self.trade_hours
        if not (lo_h <= ctx.now.hour < hi_h):
            return None

        bars = ctx.bars
        # Kanal se pocita z baru PRED aktualnim - jinak by aktualni bar
        # definoval sve vlastni maximum a proraz by nikdy nenastal.
        window = bars.iloc[-(self.channel + 1):-1]
        if len(window) < self.channel:
            return None

        upper = float(window["high"].max())
        lower = float(window["low"].min())
        close = float(bars["close"].iloc[-1])

        a = atr(bars, self.atr_period)
        if not (a > 0):
            return None
        stop_dist = self.stop_atr_mult * a

        if close > upper:
            return Order(
                side="long",
                stop_loss=close - stop_dist,
                take_profit=close + self.target_r * stop_dist,
                max_bars=self.max_bars,
                tag="donchian_long",
            )

        if self.allow_short and close < lower:
            return Order(
                side="short",
                stop_loss=close + stop_dist,
                take_profit=close - self.target_r * stop_dist,
                max_bars=self.max_bars,
                tag="donchian_short",
            )

        return None
