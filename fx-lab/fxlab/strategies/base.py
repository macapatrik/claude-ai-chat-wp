"""Zaklad pro strategie a pomocne indikatory."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..engine import Close, Context, Order


class Strategy:
    """Rozhrani strategie.

    Implementuj `on_bar`. Dostanes `Context` s historii do aktualniho baru
    VCETNE. Vratis Order, Close, nebo None.

    Prikaz se vyplni az na otevreni PRISTIHO baru. Nesnaz se to obejit -
    engine ti stejne dalsi bar neukaze.
    """

    warmup: int = 50
    params: dict = {}

    def reset(self) -> None:
        """Vola se pred kazdym behem. Vycisti vnitrni stav."""

    def on_bar(self, ctx: Context) -> Order | Close | None:
        raise NotImplementedError

    def __repr__(self) -> str:
        ps = ", ".join(f"{k}={v}" for k, v in self.params.items())
        return f"{type(self).__name__}({ps})"


# --------------------------------------------------------------------------
# Indikatory
# --------------------------------------------------------------------------


def atr(bars: pd.DataFrame, period: int = 14) -> float:
    """Average True Range poslednich `period` baru."""
    if len(bars) < period + 1:
        return float("nan")
    window = bars.iloc[-(period + 1):]
    high, low = window["high"].to_numpy(), window["low"].to_numpy()
    prev_close = window["close"].shift(1).to_numpy()
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(
            np.abs(high[1:] - prev_close[1:]), np.abs(low[1:] - prev_close[1:])
        ),
    )
    return float(np.mean(tr))


def ema(series: pd.Series, period: int) -> float:
    if len(series) < period:
        return float("nan")
    return float(series.ewm(span=period, adjust=False).mean().iloc[-1])


def rsi(series: pd.Series, period: int = 14) -> float:
    if len(series) < period + 1:
        return float("nan")
    delta = series.diff().dropna()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
    if loss == 0:
        return 100.0
    return float(100.0 - 100.0 / (1.0 + gain / loss))


def session_range(
    bars: pd.DataFrame, day: pd.Timestamp, start_hour: int, end_hour: int
) -> tuple[float, float] | None:
    """Max/min v danem hodinovem okne daneho dne (UTC).

    Vraci None, kdyz okno neni kompletni - to je dulezite, jinak bys
    obchodoval podle rozsahu, ktery jeste neskoncil.
    """
    day_start = day.normalize()
    lo = day_start + pd.Timedelta(hours=start_hour)
    hi = day_start + pd.Timedelta(hours=end_hour)
    window = bars.loc[(bars.index >= lo) & (bars.index < hi)]
    if len(window) < max(1, (end_hour - start_hour) // 2):
        return None
    return float(window["high"].max()), float(window["low"].min())
