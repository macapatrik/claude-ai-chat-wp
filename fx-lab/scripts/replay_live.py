#!/usr/bin/env python3
"""Prezene historicka data ZIVYM kodem bota a porovna s backtestem.

PROC TOHLE EXISTUJE
-------------------
Backtest a zivy bot jsou dva ruzne kusy kodu. Strategie je sice spolecna,
ale okolo ni je jinde smycka, jinde evidence pozic, jinde exekuce.

Klasicky zpusob, jak prijit o penize: backtest ukazuje zisk, zivy bot dela
neco jineho, a ty to zjistis az z vypisu z uctu.

Tenhle skript pousti obe cesty na TECH SAMYCH datech a porovna pocet
obchodu a smery. Nemusi vyjit na cent - papirovy broker plni jinak nez
backtest - ale pocet a smer obchodu sedet MUSI. Kdyz nesedi, je nekde
rozpor mezi tim, co jsi otestoval, a tim, co pobezi.

Spusteni:
    python3 scripts/replay_live.py --strategy london
    python3 scripts/replay_live.py --strategy donchian --data dukascopy
"""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from fxlab import Backtest, compute
from fxlab.costs import ZERO_COST, CostModel
from fxlab.data import clean, fetch_dukascopy, synthetic_fx
from fxlab.strategies import AsiaReversion, DonchianBreakout, LondonBreakout
from fxlive import (
    Journal, PaperBroker, RiskLimits, RiskManager, Runner, RunnerConfig, StateStore,
)

STRATEGIES = {
    "london": LondonBreakout,
    "asia": AsiaReversion,
    "donchian": DonchianBreakout,
}


class ReplayDataBroker:
    """Vydava bary postupne, jako by prichazely v realnem case.

    Zasadni: nikdy nevrati bar, ktery se jeste "neuzavrel". Tim se ziva
    cesta drzi stejneho pravidla jako backtest.
    """

    def __init__(self, bars: pd.DataFrame, warmup: int, window: int = 300):
        self.bars = bars
        self.i = warmup
        self.window = window

    def candles(self, instrument, granularity, count):
        if self.i >= len(self.bars):
            raise StopIteration
        lo = max(0, self.i - self.window + 1)
        frame = self.bars.iloc[lo: self.i + 1]
        self.i += 1
        return frame

    @property
    def exhausted(self) -> bool:
        return self.i >= len(self.bars)


def run_live_path(bars: pd.DataFrame, factory, spread_pips: float) -> dict:
    """Prozene data smyckou zive vrstvy."""
    strategy = factory()
    warmup = max(int(getattr(strategy, "warmup", 50)), 1)

    data = ReplayDataBroker(bars, warmup)
    broker = PaperBroker(balance=10_000.0, spread_pips=spread_pips)

    with tempfile.TemporaryDirectory() as tmp:
        store = StateStore(Path(tmp) / "s.json")
        journal = Journal(Path(tmp) / "j.sqlite")
        risk = RiskManager(RiskLimits(
            risk_per_trade=0.005,
            max_daily_loss=1.0,        # limity vypnuty, aby slo srovnat
            max_total_drawdown=1.0,
            max_trades_per_day=10_000,
            trade_on_weekend=True,
        ))
        cfg = RunnerConfig(instrument="EUR_USD", granularity="H1", dry_run=False)
        runner = Runner(cfg, broker, strategy, risk, store, journal,
                        data_broker=data)

        # Cenu bere papirovy broker z prave zpracovaneho baru.
        broker._price_source = lambda inst: float(bars["close"].iloc[
            min(data.i - 1, len(bars) - 1)
        ])

        runner.reconcile()

        while not data.exhausted:
            # Kontrolu SL/TP na kazdem baru dela `Runner._simulate_stops`,
            # a to PRED tim, nez bar uvidi strategie. Poradi je zasadni:
            # pozice otevrena behem baru vznikne az na jeho zaveru, takze
            # ji nesmi vykopnout pohyb, ktery probehl driv.
            try:
                runner.step()
            except StopIteration:
                break

        opens = [f for f in broker.fills if f["action"] == "open"]
        closes = [f for f in broker.fills if f["action"] == "close"]
        journal.close()

    return {
        "trades": len(opens),
        "longs": sum(1 for f in opens if f["side"] == "long"),
        "shorts": sum(1 for f in opens if f["side"] == "short"),
        "closes": len(closes),
        "final_equity": broker.account().balance,
        "first_entries": [(f["side"], round(f["price"], 5)) for f in opens[:5]],
    }


def run_backtest_path(bars: pd.DataFrame, factory, spread_pips: float) -> dict:
    costs = CostModel(spread_pips=spread_pips, slippage_pips=0.0,
                      commission_per_100k=0.0, swap_long_per_100k=0.0,
                      swap_short_per_100k=0.0)
    res = Backtest(bars, factory(), costs, initial_equity=10_000.0,
                   risk_per_trade=0.005).run()
    st = compute(res)
    return {
        "trades": st.n_trades,
        "longs": sum(1 for t in res.trades if t.side == "long"),
        "shorts": sum(1 for t in res.trades if t.side == "short"),
        "closes": st.n_trades,
        "final_equity": st.final_equity,
        "first_entries": [(t.side, round(t.entry_price, 5)) for t in res.trades[:5]],
    }


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--strategy", choices=list(STRATEGIES), default="london")
    p.add_argument("--data", choices=["synthetic", "dukascopy"], default="synthetic")
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--start", default="2023-01-01")
    p.add_argument("--end", default="2024-01-01")
    p.add_argument("--spread", type=float, default=1.2)
    args = p.parse_args()

    if args.data == "dukascopy":
        bars = clean(fetch_dukascopy(args.symbol, args.start, args.end))
    else:
        bars = synthetic_fx(start=args.start, end=args.end, seed=11)

    factory = STRATEGIES[args.strategy]
    print(f"\n{len(bars):,} baru: {bars.index[0].date()} -> {bars.index[-1].date()}")
    print(f"Strategie: {factory().__class__.__name__}, spread {args.spread} pipu\n")

    print("Backtest...")
    bt = run_backtest_path(bars, factory, args.spread)
    print("Ziva cesta...")
    lv = run_live_path(bars, factory, args.spread)

    print(f"\n{'':<18}{'backtest':>12}{'ziva cesta':>14}{'':>6}")
    print("-" * 52)
    ok = True
    for key, label in [("trades", "obchodu"), ("longs", "z toho long"),
                       ("shorts", "z toho short"), ("closes", "zavreni")]:
        same = bt[key] == lv[key]
        ok &= same
        print(f"{label:<18}{bt[key]:>12,}{lv[key]:>14,}{'  OK' if same else '  !!':>6}")

    print(f"{'konecna equity':<18}{bt['final_equity']:>12,.0f}"
          f"{lv['final_equity']:>14,.0f}{'':>6}")

    print("\nPrvni obchody:")
    print(f"  backtest:   {bt['first_entries']}")
    print(f"  ziva cesta: {lv['first_entries']}")

    print()
    if ok:
        print("SEDI. Ziva cesta dela to same, co jsi otestoval v backtestu.")
        print("Rozdil v equity je z jineho modelu plneni, ne z jine logiky.\n")
        return 0

    print("NESEDI. Ziva vrstva se chova jinak nez backtest.")
    print("Nenasazuj, dokud nezjistis proc.\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
