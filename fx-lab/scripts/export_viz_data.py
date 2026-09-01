#!/usr/bin/env python3
"""Vyexportuje vysledky backtestu do JSON pro vizualizaci.

Vsechna cisla v grafech pochazi odsud - nic se nedopisuje rucne.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from fxlab import Backtest, compute, grid, walk_forward
from fxlab.costs import OANDA_EURUSD, ECN_EURUSD, ZERO_COST
from fxlab.data import synthetic_fx
from fxlab.strategies import AsiaReversion, DonchianBreakout, LondonBreakout

STRATS = {
    "London breakout": LondonBreakout,
    "Asia reversion": AsiaReversion,
    "Donchian breakout": DonchianBreakout,
}


def downsample(curve: pd.Series, points: int = 320) -> list[dict]:
    """Zredukuje equity krivku na rozumny pocet bodu pro graf."""
    if len(curve) <= points:
        sampled = curve
    else:
        step = len(curve) // points
        sampled = curve.iloc[::step]
    return [
        {"t": ts.strftime("%Y-%m-%d"), "v": round(float(v), 2)}
        for ts, v in sampled.items()
    ]


def stats_dict(st) -> dict:
    def clean(x):
        if isinstance(x, (int, np.integer)):
            return int(x)
        x = float(x)
        return None if (np.isnan(x) or np.isinf(x)) else round(x, 4)

    return {k: clean(v) for k, v in st.to_dict().items()}


def main() -> None:
    bars = synthetic_fx(start="2021-01-01", end="2026-01-01", seed=7)
    out: dict = {
        "generated_from": "synthetic_fx(seed=7)",
        "warning": "Synteticka data - nahodny proces bez hrany. "
                   "Cisla ukazuji chovani ENGINU, ne ziskovost strategii.",
        "period": {"start": str(bars.index[0].date()),
                   "end": str(bars.index[-1].date()),
                   "bars": len(bars)},
        "strategies": {},
        "sanity": {},
        "walkforward": {},
    }

    # --- Backtesty se dvema urovnemi nakladu -----------------------------
    for name, factory in STRATS.items():
        entry: dict = {}
        for label, costs in (("zero", ZERO_COST), ("oanda", OANDA_EURUSD),
                             ("ecn", ECN_EURUSD)):
            res = Backtest(bars, factory(), costs, initial_equity=10_000.0,
                           risk_per_trade=0.005).run()
            st = compute(res)
            entry[label] = {
                "stats": stats_dict(st),
                "curve": downsample(res.equity_curve),
            }
            if label == "oanda":
                entry["r_multiples"] = [round(t.r_multiple, 3)
                                        for t in res.trades]
                reasons: dict = {}
                for t in res.trades:
                    reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1
                entry["exit_reasons"] = reasons
        out["strategies"][name] = entry
        print(f"  {name}: hotovo")

    # --- Sanity check napric seedy ---------------------------------------
    print("Sanity check...")
    for name, factory in STRATS.items():
        rows = {"zero": [], "oanda": []}
        for seed in range(1, 13):
            b = synthetic_fx(start="2021-01-01", end="2025-01-01", seed=seed)
            for label, costs in (("zero", ZERO_COST), ("oanda", OANDA_EURUSD)):
                st = compute(Backtest(b, factory(), costs,
                                      initial_equity=10_000.0,
                                      risk_per_trade=0.005).run())
                if st.n_trades >= 20:
                    rows[label].append(st.expectancy_r)
        out["sanity"][name] = {
            "zero_mean": round(float(np.mean(rows["zero"])), 4),
            "zero_values": [round(v, 4) for v in rows["zero"]],
            "oanda_mean": round(float(np.mean(rows["oanda"])), 4),
            "oanda_values": [round(v, 4) for v in rows["oanda"]],
            "n_runs": len(rows["zero"]),
        }
        print(f"  {name}: hotovo")

    # --- Walk-forward -----------------------------------------------------
    print("Walk-forward...")
    windows, oos = walk_forward(
        bars, DonchianBreakout,
        grid(channel=[24, 48, 96], stop_atr_mult=[1.5, 2.0, 3.0]),
        OANDA_EURUSD, train_months=12, test_months=3, verbose=False,
    )
    out["walkforward"] = {
        "strategy": "Donchian breakout",
        "windows": [
            {
                "test_start": str(w.test_start.date()),
                "test_end": str(w.test_end.date()),
                "train_expectancy": round(w.train_stats.expectancy_r, 4),
                "test_expectancy": round(w.test_stats.expectancy_r, 4),
                "test_trades": w.test_stats.n_trades,
                "params": {k: (list(v) if isinstance(v, tuple) else v)
                           for k, v in w.best_params.items()},
            }
            for w in windows
        ],
        "oos_stats": stats_dict(compute(oos)) if oos else None,
    }

    dest = Path(__file__).resolve().parents[1] / "viz_data.json"
    dest.write_text(json.dumps(out, indent=1))
    print(f"\nUlozeno: {dest}  ({dest.stat().st_size / 1024:.0f} kB)")


if __name__ == "__main__":
    main()
