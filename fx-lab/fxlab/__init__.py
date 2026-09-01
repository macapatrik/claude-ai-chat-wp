"""fxlab - poctivy backtest framework pro intradenni FX.

Navrzeny tak, aby ti nelhal. Konkretne:
  - strategie nikdy nevidi budouci data (vynuceno strukturou engine)
  - naklady se uctuji zvlast, aby bylo videt, kolik zeru
  - metriky ukazuji i drawdown a jeho delku, ne jen vynos
  - walk-forward odhali preoptimalizovani

Rychly start:

    from fxlab import Backtest, OANDA_EURUSD, compute, format_report
    from fxlab.data import fetch_dukascopy, clean
    from fxlab.strategies import LondonBreakout

    bars = clean(fetch_dukascopy("EURUSD", "2022-01-01", "2026-01-01"))
    res = Backtest(bars, LondonBreakout(), OANDA_EURUSD).run()
    print(format_report(res))
"""

from .costs import CostModel, OANDA_EURUSD, ECN_EURUSD, ZERO_COST
from .engine import Backtest, Close, Context, Order, Position, Result, Trade
from .metrics import Stats, compute, format_report
from .walkforward import grid, walk_forward, format_windows

__version__ = "0.1.0"

__all__ = [
    "CostModel", "OANDA_EURUSD", "ECN_EURUSD", "ZERO_COST",
    "Backtest", "Close", "Context", "Order", "Position", "Result", "Trade",
    "Stats", "compute", "format_report",
    "grid", "walk_forward", "format_windows",
]
