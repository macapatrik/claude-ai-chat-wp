#!/usr/bin/env python3
"""Spusti backtest strategie na realnych nebo syntetickych datech.

Priklady
--------
Syntetika (funguje hned, ale nic nedokazuje o ziskovosti):

    python3 scripts/run_backtest.py --strategy london --data synthetic

Realna data z Dukascopy (prvni beh trva 10-20 minut, pak jede z cache):

    python3 scripts/run_backtest.py --strategy london \\
        --data dukascopy --symbol EURUSD --start 2022-01-01 --end 2026-01-01

Data primo od OANDA (potrebuje OANDA_TOKEN v prostredi):

    export OANDA_TOKEN="..."
    python3 scripts/run_backtest.py --strategy donchian --data oanda

Walk-forward misto jednoho behu:

    python3 scripts/run_backtest.py --strategy london --data dukascopy \\
        --start 2020-01-01 --end 2026-01-01 --walkforward
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from fxlab import Backtest, compute, format_report, format_windows, grid, walk_forward
from fxlab.costs import CostModel, ECN_EURUSD, OANDA_EURUSD, ZERO_COST
from fxlab.data import clean, fetch_dukascopy, fetch_oanda, load_csv, pip_size_for, synthetic_fx
from fxlab.strategies import AsiaReversion, DonchianBreakout, LondonBreakout

STRATEGIES = {
    "london": LondonBreakout,
    "asia": AsiaReversion,
    "donchian": DonchianBreakout,
}

COSTS = {"oanda": OANDA_EURUSD, "ecn": ECN_EURUSD, "zero": ZERO_COST}

# Male, zamerne skromne mrizky. Cim vic kombinaci, tim vetsi sance, ze
# "nejlepsi" vysledek je jen nejlepe padnouci sum.
WF_GRIDS = {
    "london": dict(stop_atr_mult=[0.75, 1.0, 1.5], target_r=[1.0, 1.5, 2.0]),
    "asia": dict(entry_atr_mult=[1.0, 1.5, 2.0], stop_atr_mult=[1.0, 1.5, 2.0]),
    "donchian": dict(channel=[24, 48, 96], stop_atr_mult=[1.5, 2.0, 3.0]),
}


def load_bars(args) -> pd.DataFrame:
    if args.data == "synthetic":
        print("!" * 66)
        print("! SYNTETICKA DATA - nahodny proces bez jakekoli hrany.")
        print("! Slouzi VYHRADNE k overeni, ze engine pocita spravne.")
        print("! O ziskovosti strategie ti nerekne vubec nic.")
        print("!" * 66)
        return synthetic_fx(start=args.start, end=args.end, timeframe=args.timeframe)

    if args.data == "dukascopy":
        bars = fetch_dukascopy(
            args.symbol, args.start, args.end, timeframe=args.timeframe
        )
        return clean(bars)

    if args.data == "oanda":
        instrument = args.symbol if "_" in args.symbol else f"{args.symbol[:3]}_{args.symbol[3:]}"
        gran = {"1h": "H1", "4h": "H4", "15min": "M15", "5min": "M5"}.get(
            args.timeframe, "H1"
        )
        return clean(fetch_oanda(instrument, granularity=gran, count=5000))

    if args.data == "csv":
        if not args.csv:
            sys.exit("--data csv vyzaduje --csv cesta/k/souboru.csv")
        return clean(load_csv(args.csv))

    sys.exit(f"Neznamy zdroj dat: {args.data}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--strategy", choices=list(STRATEGIES), default="london")
    p.add_argument("--data", choices=["synthetic", "dukascopy", "oanda", "csv"],
                   default="synthetic")
    p.add_argument("--csv", help="Cesta k CSV, kdyz --data csv")
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--start", default="2021-01-01")
    p.add_argument("--end", default="2026-01-01")
    p.add_argument("--timeframe", default="1h")
    p.add_argument("--costs", choices=list(COSTS), default="oanda")
    p.add_argument("--equity", type=float, default=10_000.0)
    p.add_argument("--risk", type=float, default=0.005,
                   help="Podil equity v riziku na obchod (0.005 = 0.5 %%)")
    p.add_argument("--walkforward", action="store_true")
    p.add_argument("--train-months", type=int, default=12)
    p.add_argument("--test-months", type=int, default=3)
    p.add_argument("--save-trades", help="Ulozit obchody do CSV")
    args = p.parse_args()

    bars = load_bars(args)
    print(f"\nNacteno {len(bars):,} baru: {bars.index[0]} -> {bars.index[-1]}")

    costs = COSTS[args.costs]
    pip = pip_size_for(args.symbol)
    if pip != costs.pip_size:
        costs = CostModel(**{**costs.__dict__, "pip_size": pip})

    factory = STRATEGIES[args.strategy]

    if args.walkforward:
        print(f"\nWalk-forward: {args.train_months}m trenink / "
              f"{args.test_months}m test\n")
        param_grid = grid(**WF_GRIDS[args.strategy])
        print(f"Mrizka: {len(param_grid)} kombinaci na okno\n")

        windows, oos = walk_forward(
            bars, factory, param_grid, costs,
            train_months=args.train_months, test_months=args.test_months,
            initial_equity=args.equity, risk_per_trade=args.risk,
        )
        print(format_windows(windows))

        if oos is None:
            print("\nZadne obchody mimo vzorek. Strategie je prilis vyberova.")
            return
        print("\n\nSOUHRN MIMO VZOREK (jedine cislo, na kterem zalezi):")
        print(format_report(oos))
        return

    strategy = factory()
    print(f"Strategie: {strategy}")
    print(f"Naklady:   spread {costs.spread_pips} pip, "
          f"slippage {costs.slippage_pips} pip, "
          f"komise {costs.commission_per_100k} USD/lot\n")

    result = Backtest(
        bars, strategy, costs,
        initial_equity=args.equity, risk_per_trade=args.risk,
    ).run()

    print(format_report(result))

    if result.rejected_orders:
        print(f"  Odmitnutych prikazu: {result.rejected_orders} "
              f"(gap pres stop pri vstupu)\n")

    if args.save_trades and result.trades:
        df = pd.DataFrame([
            {"entry_time": t.entry_time, "exit_time": t.exit_time,
             "side": t.side, "entry": t.entry_price, "exit": t.exit_price,
             "units": round(t.units), "gross": t.gross_pnl, "costs": t.costs,
             "swap": t.swap, "net": t.net_pnl, "r": t.r_multiple,
             "reason": t.exit_reason, "bars": t.bars_held}
            for t in result.trades
        ])
        df.to_csv(args.save_trades, index=False)
        print(f"  Obchody ulozeny: {args.save_trades}")


if __name__ == "__main__":
    main()
