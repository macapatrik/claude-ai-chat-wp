#!/usr/bin/env python3
"""Kontrola, ze engine nevyrabi zisk z niceho.

CO SE TESTUJE
-------------
Na cistě nahodnych datech nemuze existovat zadna hrana. Kdyz na nich
strategie vydelava, je chyba v enginu - nejcasteji look-ahead.

Postup:
  1. Vygeneruje se N nezavislych nahodnych radu (ruzne seedy).
  2. Kazda strategie se na nich spusti bez nakladu.
  3. Prumerna expectancy musi vyjit kolem nuly.
  4. S naklady musi vyjit ZAPORNA - naklady jsou jediny jisty vysledek.

Bod 4 je nejdulezitejsi. Presne tohle ceka kazdou strategii bez skutecne
hrany na realnem trhu.

Spusteni:  python3 scripts/sanity_check.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from fxlab import Backtest, compute
from fxlab.costs import OANDA_EURUSD, ZERO_COST
from fxlab.data import synthetic_fx
from fxlab.strategies import AsiaReversion, DonchianBreakout, LondonBreakout

N_RUNS = 12
STRATS = {
    "LondonBreakout": LondonBreakout,
    "AsiaReversion": AsiaReversion,
    "DonchianBreakout": DonchianBreakout,
}


def run_set(factory, costs, seeds) -> tuple[np.ndarray, np.ndarray]:
    exps, trades = [], []
    for seed in seeds:
        bars = synthetic_fx(start="2021-01-01", end="2025-01-01", seed=seed)
        res = Backtest(bars, factory(), costs, initial_equity=10_000.0,
                       risk_per_trade=0.005).run()
        st = compute(res)
        if st.n_trades >= 20:
            exps.append(st.expectancy_r)
            trades.append(st.n_trades)
    return np.array(exps), np.array(trades)


def main() -> None:
    seeds = list(range(1, N_RUNS + 1))
    print(f"\nKontrola enginu na {N_RUNS} nezavislych nahodnych radech")
    print("(4 roky hodinovych dat na beh)\n")
    print(f"{'strategie':<20} {'E[R] bez nakl.':>16} {'E[R] s naklady':>16} "
          f"{'obchodu':>10}")
    print("-" * 66)

    failures = []
    for name, factory in STRATS.items():
        free_exp, free_n = run_set(factory, ZERO_COST, seeds)
        cost_exp, _ = run_set(factory, OANDA_EURUSD, seeds)

        if len(free_exp) == 0:
            print(f"{name:<20} {'prilis malo obchodu':>44}")
            continue

        m_free, m_cost = free_exp.mean(), cost_exp.mean()
        se = free_exp.std(ddof=1) / np.sqrt(len(free_exp)) if len(free_exp) > 1 else 0.0

        print(f"{name:<20} {m_free:>+16.4f} {m_cost:>+16.4f} "
              f"{int(free_n.mean()):>10,}")

        # Bez nakladu musi byt expectancy statisticky nerozlisitelna od nuly.
        if se > 0 and abs(m_free) > 3 * se:
            failures.append(
                f"{name}: E[R] bez nakladu = {m_free:+.4f}, "
                f"{abs(m_free)/se:.1f} smerodatnych chyb od nuly. "
                f"Na nahodnych datech nema co vydelavat -> podezreni na "
                f"look-ahead v enginu nebo ve strategii."
            )
        # S naklady musi byt zaporna.
        if m_cost >= 0:
            failures.append(
                f"{name}: E[R] s naklady = {m_cost:+.4f}, ceka se zaporna. "
                f"Naklady se pravdepodobne neuctuji."
            )

    print("-" * 66)
    if failures:
        print("\nPROBLEM:\n")
        for f in failures:
            print(f"  - {f}\n")
        sys.exit(1)

    print("\nOK. Engine na nahodnych datech nevydelava a naklady se uctuji.")
    print("To neznamena, ze nejaka strategie funguje - jen ze merak meri.\n")


if __name__ == "__main__":
    main()
