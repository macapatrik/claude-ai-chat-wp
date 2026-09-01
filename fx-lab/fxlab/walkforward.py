"""Walk-forward analyza - test na preoptimalizovani.

PROC TO POTREBUJES
------------------
Kdyz na jednom kusu historie vyzkousis 200 kombinaci parametru a vybereš
tu nejlepsi, NASEL JSI SUM. Vzdycky nejaka kombinace vyjde skvele, i kdyz
zadna hrana neexistuje. Cim vic parametru, tim jistejsi ten klam je.

Walk-forward to odhali. Parametry se ladi na trenovacim okne a testuji na
nasledujicim, ktere model nikdy nevidel. Pak se okno posune.

JAK CIST VYSLEDEK
-----------------
Rozhoduje SOUHRN Z TESTOVACICH OKEN, nikdy z trenovacich.

Zdrave chovani:
  - testovaci vysledek je slabsi nez trenovaci (vzdycky je)
  - ale porad kladny a napric okny konzistentni
  - vybrane parametry se mezi okny prilis nemeni

Varovne signaly:
  - trenovaci Sharpe 2.5, testovaci 0.1  -> ciste preoptimalizovani
  - parametry skacou z okna na okno      -> zadna stabilni hrana
  - jedno okno nese cely zisk            -> jednorazova nahoda
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

import numpy as np
import pandas as pd

from .costs import CostModel
from .engine import Backtest, Result, Trade
from .metrics import Stats, compute


@dataclass
class WindowResult:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    best_params: dict
    train_stats: Stats
    test_stats: Stats
    test_trades: list[Trade]


def _score(stats: Stats) -> float:
    """Kriterium vyberu parametru.

    Zamerne NENI celkovy vynos - ten se optimalizuje nejsnaz a nejhur se
    drzi. Pouziva se expectancy v R vazena poctem obchodu, s penalizaci
    za drawdown a s tvrdym minimem na pocet obchodu.
    """
    if stats.n_trades < 25:
        return -np.inf
    if np.isnan(stats.expectancy_r):
        return -np.inf
    dd_penalty = 1.0 + max(0.0, -stats.max_drawdown_pct) / 100.0
    return stats.expectancy_r * np.sqrt(stats.n_trades) / dd_penalty


def grid(**kwargs: Sequence) -> list[dict]:
    """Kartezsky soucin parametru.

        grid(channel=[24, 48], stop_atr_mult=[1.5, 2.0])
        -> 4 kombinace

    Drz to male. 5 parametru po 5 hodnotach = 3125 kombinaci, a s tolika
    pokusy najdes "ziskovou" strategii i v nahodnem sumu.
    """
    keys = list(kwargs)
    return [dict(zip(keys, vals)) for vals in itertools.product(*kwargs.values())]


def walk_forward(
    bars: pd.DataFrame,
    strategy_factory: Callable[..., object],
    param_grid: list[dict],
    costs: CostModel,
    train_months: int = 12,
    test_months: int = 3,
    initial_equity: float = 10_000.0,
    risk_per_trade: float = 0.005,
    verbose: bool = True,
) -> tuple[list[WindowResult], Result | None]:
    """Spusti walk-forward.

    Vraci (jednotliva okna, Result slozeny jen z obchodu MIMO VZOREK).
    Ten druhy je jedine cislo, na kterem zalezi.
    """
    windows: list[WindowResult] = []
    start = bars.index[0]
    end = bars.index[-1]

    train_delta = pd.DateOffset(months=train_months)
    test_delta = pd.DateOffset(months=test_months)

    train_start = start
    while True:
        train_end = train_start + train_delta
        test_end = train_end + test_delta
        if test_end > end:
            break

        train = bars.loc[train_start:train_end]
        test = bars.loc[train_end:test_end]
        if len(train) < 200 or len(test) < 50:
            train_start = train_start + test_delta
            continue

        best_score, best_params, best_train = -np.inf, None, None
        for params in param_grid:
            try:
                res = Backtest(
                    train, strategy_factory(**params), costs,
                    initial_equity=initial_equity, risk_per_trade=risk_per_trade,
                ).run()
            except (ValueError, RuntimeError):
                continue
            st = compute(res)
            sc = _score(st)
            if sc > best_score:
                best_score, best_params, best_train = sc, params, st

        if best_params is None:
            if verbose:
                print(f"  {train_end.date()}: zadna kombinace neprosla filtrem")
            train_start = train_start + test_delta
            continue

        test_res = Backtest(
            test, strategy_factory(**best_params), costs,
            initial_equity=initial_equity, risk_per_trade=risk_per_trade,
        ).run()
        test_stats = compute(test_res)

        windows.append(
            WindowResult(
                train_start=train_start, train_end=train_end,
                test_start=train_end, test_end=test_end,
                best_params=best_params,
                train_stats=best_train, test_stats=test_stats,
                test_trades=test_res.trades,
            )
        )

        if verbose:
            print(
                f"  {train_end.date()} -> {test_end.date()}: "
                f"train E={best_train.expectancy_r:+.3f}R  "
                f"test E={test_stats.expectancy_r:+.3f}R "
                f"({test_stats.n_trades} obch.)  {best_params}"
            )

        train_start = train_start + test_delta

    return windows, _aggregate(windows, initial_equity, costs)


def _aggregate(
    windows: list[WindowResult], initial_equity: float, costs: CostModel
) -> Result | None:
    """Slozi obchody ze vsech testovacich oken do jedne equity krivky.

    Vraci Result, aby na nej sel pustit stejny `format_report` jako na
    obycejny backtest.
    """
    if not windows:
        return None

    trades = [t for w in windows for t in w.test_trades]
    if not trades:
        return None
    trades.sort(key=lambda t: t.exit_time)

    equity = initial_equity
    times, values = [], []
    for t in trades:
        equity += t.net_pnl
        times.append(t.exit_time)
        values.append(equity)

    curve = pd.Series(values, index=pd.DatetimeIndex(times), name="equity")
    curve = curve[~curve.index.duplicated(keep="last")]

    return Result(
        trades=trades, equity_curve=curve, initial_equity=initial_equity,
        costs=costs,
        meta={
            "strategy": "walk-forward, jen mimo vzorek",
            "start": str(windows[0].test_start),
            "end": str(windows[-1].test_end),
            "bars": len(curve),
            "risk_per_trade": 0.0,
        },
    )


def format_windows(windows: list[WindowResult]) -> str:
    """Tabulka train vs test - hlavni pohled na preoptimalizovani."""
    if not windows:
        return "Zadna okna. Bud je dat malo, nebo zadna kombinace neprosla filtrem."

    lines = [
        "",
        f"{'okno (test)':<24} {'train E[R]':>11} {'test E[R]':>11} {'test obch.':>11} {'test DD':>9}",
        "-" * 72,
    ]
    for w in windows:
        lines.append(
            f"{str(w.test_start.date()) + ' -> ' + str(w.test_end.date()):<24} "
            f"{w.train_stats.expectancy_r:>+11.3f} "
            f"{w.test_stats.expectancy_r:>+11.3f} "
            f"{w.test_stats.n_trades:>11d} "
            f"{w.test_stats.max_drawdown_pct:>8.1f}%"
        )

    tr = np.mean([w.train_stats.expectancy_r for w in windows])
    te = np.mean([w.test_stats.expectancy_r for w in windows])
    lines += ["-" * 72, f"{'prumer':<24} {tr:>+11.3f} {te:>+11.3f}"]

    if tr > 0 and te < tr * 0.3:
        lines.append(
            "\n  POZOR: testovaci vysledek je mnohem horsi nez trenovaci.\n"
            "  Typicky podpis preoptimalizovani. Uber parametry."
        )
    return "\n".join(lines)
