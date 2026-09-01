"""Vyhodnoceni backtestu.

Zamerne se tu pocita vic "nepohodlnych" metrik nez v typickem reportu.
Prodejci botu ukazuji vynos a win rate. To jsou dve nejmene uzitecna cisla.

Co opravdu rozhoduje:
  - max drawdown a jeho DELKA (kolik mesicu jsi pod vodou)
  - cost drag (kolik z hrube hrany sezraly naklady)
  - expectancy v R (ocekavany vysledek na jeden obchod)
  - pocet obchodu (30 obchodu nic nedokazuje, at je vysledek jakykoli)
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

from .engine import Result

TRADING_DAYS = 252


@dataclass
class Stats:
    # Vynos
    total_return_pct: float
    cagr_pct: float
    final_equity: float

    # Riziko
    max_drawdown_pct: float
    max_drawdown_days: float
    sharpe: float
    sortino: float
    calmar: float

    # Obchody
    n_trades: int
    win_rate_pct: float
    profit_factor: float
    expectancy_r: float
    avg_win_r: float
    avg_loss_r: float
    best_trade_r: float
    worst_trade_r: float
    avg_bars_held: float
    max_consecutive_losses: int

    # Naklady - u intradenniho FX obvykle rozhodujici
    gross_pnl: float
    total_costs: float
    total_swap: float
    net_pnl: float
    cost_drag_pct: float
    """Kolik procent z hrubeho zisku sezraly naklady. Nad 100 % = naklady
    prevysily hranu a strategie je ztratova jen kvuli nim."""

    def to_dict(self) -> dict:
        return asdict(self)


def _max_drawdown(curve: pd.Series) -> tuple[float, float]:
    """Vraci (hloubka v %, nejdelsi trvani ve dnech)."""
    running_max = curve.cummax()
    dd = curve / running_max - 1.0
    depth = float(dd.min() * 100.0)

    # Nejdelsi obdobi pod predchozim maximem.
    under = dd < -1e-12
    longest = pd.Timedelta(0)
    start = None
    for ts, is_under in under.items():
        if is_under and start is None:
            start = ts
        elif not is_under and start is not None:
            longest = max(longest, ts - start)
            start = None
    if start is not None:
        longest = max(longest, under.index[-1] - start)

    return depth, longest.total_seconds() / 86400.0


def _annualisation_factor(curve: pd.Series) -> float:
    """Kolik period pripada na rok - odvozeno z realneho rozestupu baru."""
    if len(curve) < 3:
        return TRADING_DAYS
    median_delta = pd.Series(curve.index).diff().median()
    if pd.isna(median_delta) or median_delta.total_seconds() <= 0:
        return TRADING_DAYS
    # FX bezi ~120 hodin tydne, tedy ~6260 hodin rocne.
    seconds_per_year = 6260 * 3600
    return seconds_per_year / median_delta.total_seconds()


def compute(result: Result) -> Stats:
    curve = result.equity_curve
    trades = result.trades
    init = result.initial_equity
    final = float(curve.iloc[-1])

    total_return = (final / init - 1.0) * 100.0

    span_days = (curve.index[-1] - curve.index[0]).total_seconds() / 86400.0
    years = max(span_days / 365.25, 1e-9)
    cagr = ((final / init) ** (1.0 / years) - 1.0) * 100.0 if final > 0 else -100.0

    dd_depth, dd_days = _max_drawdown(curve)

    rets = curve.pct_change().dropna()
    ann = _annualisation_factor(curve)
    if len(rets) > 1 and rets.std() > 0:
        sharpe = float(rets.mean() / rets.std() * np.sqrt(ann))
        downside = rets[rets < 0]
        sortino = (
            float(rets.mean() / downside.std() * np.sqrt(ann))
            if len(downside) > 1 and downside.std() > 0
            else float("nan")
        )
    else:
        sharpe = sortino = float("nan")

    calmar = cagr / abs(dd_depth) if dd_depth < -1e-9 else float("nan")

    n = len(trades)
    if n == 0:
        return Stats(
            total_return_pct=total_return, cagr_pct=cagr, final_equity=final,
            max_drawdown_pct=dd_depth, max_drawdown_days=dd_days,
            sharpe=sharpe, sortino=sortino, calmar=calmar,
            n_trades=0, win_rate_pct=float("nan"), profit_factor=float("nan"),
            expectancy_r=float("nan"), avg_win_r=float("nan"),
            avg_loss_r=float("nan"), best_trade_r=float("nan"),
            worst_trade_r=float("nan"), avg_bars_held=float("nan"),
            max_consecutive_losses=0,
            gross_pnl=0.0, total_costs=0.0, total_swap=0.0, net_pnl=0.0,
            cost_drag_pct=float("nan"),
        )

    nets = np.array([t.net_pnl for t in trades])
    rs = np.array([t.r_multiple for t in trades])
    wins, losses = nets[nets > 0], nets[nets <= 0]

    gross_profit = float(wins.sum())
    gross_loss = float(-losses.sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    streak = best_streak = 0
    for t in trades:
        if t.net_pnl <= 0:
            streak += 1
            best_streak = max(best_streak, streak)
        else:
            streak = 0

    gross = float(sum(t.gross_pnl for t in trades))
    costs = float(sum(t.costs for t in trades))
    swap = float(sum(t.swap for t in trades))
    cost_drag = (costs + swap) / abs(gross) * 100.0 if abs(gross) > 1e-9 else float("nan")

    return Stats(
        total_return_pct=total_return,
        cagr_pct=cagr,
        final_equity=final,
        max_drawdown_pct=dd_depth,
        max_drawdown_days=dd_days,
        sharpe=sharpe,
        sortino=sortino,
        calmar=calmar,
        n_trades=n,
        win_rate_pct=float(len(wins) / n * 100.0),
        profit_factor=profit_factor,
        expectancy_r=float(rs.mean()),
        avg_win_r=float(rs[rs > 0].mean()) if (rs > 0).any() else 0.0,
        avg_loss_r=float(rs[rs <= 0].mean()) if (rs <= 0).any() else 0.0,
        best_trade_r=float(rs.max()),
        worst_trade_r=float(rs.min()),
        avg_bars_held=float(np.mean([t.bars_held for t in trades])),
        max_consecutive_losses=best_streak,
        gross_pnl=gross,
        total_costs=costs,
        total_swap=swap,
        net_pnl=gross - costs - swap,
        cost_drag_pct=cost_drag,
    )


def format_report(result: Result, stats: Stats | None = None) -> str:
    """Textovy report do konzole."""
    s = stats or compute(result)
    m = result.meta

    def f(x, suffix="", nd=2):
        if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
            return "n/a"
        return f"{x:,.{nd}f}{suffix}"

    verdict = _verdict(s)

    return f"""
{'=' * 66}
 {m.get('strategy', '?')}   {m.get('start', '')[:10]} -> {m.get('end', '')[:10]}
 {m.get('bars', 0):,} baru | riziko {m.get('risk_per_trade', 0) * 100:.2f} % na obchod
{'=' * 66}

 VYNOS
   Celkovy vynos           {f(s.total_return_pct, ' %')}
   CAGR                    {f(s.cagr_pct, ' %')}
   Konecna equity          {f(s.final_equity, ' USD')}

 RIZIKO
   Max drawdown            {f(s.max_drawdown_pct, ' %')}
   Nejdelsi pod vodou      {f(s.max_drawdown_days, ' dni', 0)}
   Sharpe                  {f(s.sharpe)}
   Sortino                 {f(s.sortino)}
   Calmar                  {f(s.calmar)}

 OBCHODY
   Pocet                   {s.n_trades:,}
   Uspesnost               {f(s.win_rate_pct, ' %')}
   Profit factor           {f(s.profit_factor)}
   Expectancy              {f(s.expectancy_r, ' R')}
   Prumerny zisk / ztrata  {f(s.avg_win_r, ' R')} / {f(s.avg_loss_r, ' R')}
   Nejlepsi / nejhorsi     {f(s.best_trade_r, ' R')} / {f(s.worst_trade_r, ' R')}
   Max ztrat za sebou      {s.max_consecutive_losses}
   Prumerne drzeni         {f(s.avg_bars_held, ' baru', 1)}

 NAKLADY
   Hrube P&L               {f(s.gross_pnl, ' USD')}
   Spread + komise         {f(-s.total_costs, ' USD')}
   Swapy                   {f(-s.total_swap, ' USD')}
   Ciste P&L               {f(s.net_pnl, ' USD')}
   Naklady / hruby zisk    {f(s.cost_drag_pct, ' %')}

 {verdict}
{'=' * 66}
"""


def _verdict(s: Stats) -> str:
    """Strohe zhodnoceni. Radeji falesne negativni nez falesne pozitivni."""
    problems = []
    if s.n_trades < 100:
        problems.append(f"jen {s.n_trades} obchodu - statisticky bezcenne")
    if not np.isnan(s.expectancy_r) and s.expectancy_r <= 0:
        problems.append(f"zaporna expectancy ({s.expectancy_r:.3f} R)")
    if not np.isnan(s.cost_drag_pct) and s.cost_drag_pct > 100:
        problems.append("naklady prevysily hrubou hranu")
    if s.max_drawdown_pct < -30:
        problems.append(f"drawdown {s.max_drawdown_pct:.0f} % - neuobchodovatelne")
    if not np.isnan(s.sharpe) and s.sharpe < 0.5:
        problems.append(f"Sharpe {s.sharpe:.2f} pod 0.5")
    if s.max_drawdown_days > 365:
        problems.append(f"{s.max_drawdown_days:.0f} dni pod vodou")

    if not problems:
        return "VERDIKT: prosla zakladnimi filtry. Dalsi krok je walk-forward."
    return "VERDIKT: NENASAZOVAT\n   - " + "\n   - ".join(problems)
