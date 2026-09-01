"""London breakout - proraz asijskeho rozsahu na otevreni Londyna.

MYSLENKA
--------
Asijska session je klidna a uzka. Kdyz v 07:00 UTC otevre Londyn, prijde
objem a cena casto vystreli z nocniho rozsahu. Obchoduje se ve smeru prorazu.

REALITA
-------
Tohle je jedna z nejznamejsich a nejzverejnenejsich FX strategii. Cokoli,
co zna kazdy, byva zarbitrazovane. Ceka fale sesny proraz - cena vystreli
z rozsahu a hned se vrati. Ber ji jako referencni bod, ne jako objev.

Filtry, ktere maji smysl otestovat:
  - minimalni sirka rozsahu (uzky rozsah = vic falesnych prorazu)
  - maximalni sirka rozsahu (siroky = pohyb uz probehl)
  - jen jeden obchod denne
"""

from __future__ import annotations

import pandas as pd

from ..engine import Close, Context, Order
from .base import Strategy, atr, session_range


class LondonBreakout(Strategy):
    def __init__(
        self,
        asia_start: int = 0,
        asia_end: int = 7,
        trade_until: int = 12,
        close_at: int = 20,
        stop_atr_mult: float = 1.0,
        target_r: float = 1.5,
        min_range_atr: float = 0.5,
        max_range_atr: float = 3.0,
        atr_period: int = 24,
        buffer_pips: float = 1.0,
        pip: float = 0.0001,
    ):
        self.params = dict(
            asia_start=asia_start, asia_end=asia_end, trade_until=trade_until,
            close_at=close_at, stop_atr_mult=stop_atr_mult, target_r=target_r,
            min_range_atr=min_range_atr, max_range_atr=max_range_atr,
            atr_period=atr_period, buffer_pips=buffer_pips,
        )
        self.__dict__.update(self.params)
        self.pip = pip
        self.warmup = max(atr_period + 2, 50)
        self._traded_on: set = set()

    def reset(self) -> None:
        self._traded_on = set()

    def on_bar(self, ctx: Context) -> Order | Close | None:
        now = ctx.now
        hour = now.hour

        # Konec dne - zavrit vse, pres noc nedrzime (swapy a gapy).
        if ctx.position is not None:
            if hour >= self.close_at:
                return Close("session_end")
            return None

        # Obchodujeme jen v okne po otevreni Londyna.
        if not (self.asia_end <= hour < self.trade_until):
            return None

        day_key = now.normalize()
        if day_key in self._traded_on:
            return None

        rng = session_range(ctx.bars, now, self.asia_start, self.asia_end)
        if rng is None:
            return None
        hi, lo = rng
        width = hi - lo

        a = atr(ctx.bars, self.atr_period)
        if not (a > 0) or width <= 0:
            return None

        # Filtr sirky rozsahu.
        if not (self.min_range_atr * a <= width <= self.max_range_atr * a):
            return None

        close = float(ctx.last["close"])
        buf = self.buffer_pips * self.pip
        stop_dist = self.stop_atr_mult * a

        if close > hi + buf:
            self._traded_on.add(day_key)
            sl = close - stop_dist
            return Order(
                side="long", stop_loss=sl,
                take_profit=close + self.target_r * stop_dist,
                tag="london_long",
            )

        if close < lo - buf:
            self._traded_on.add(day_key)
            sl = close + stop_dist
            return Order(
                side="short", stop_loss=sl,
                take_profit=close - self.target_r * stop_dist,
                tag="london_short",
            )

        return None
