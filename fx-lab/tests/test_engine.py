"""Testy, ktere dokazuji, ze engine nelze.

Kazdy z techto testu overuje jednu konkretni chybu, kterou amaterske
backtesty delaji a ktera vyrobi falesne ziskovou strategii.

Spusteni:  python3 -m pytest tests/ -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fxlab.costs import CostModel, ZERO_COST
from fxlab.engine import Backtest, Close, Context, Order
from fxlab.strategies.base import Strategy


def make_bars(rows, start="2024-01-02 00:00", freq="1h"):
    """rows = seznam (open, high, low, close)."""
    idx = pd.date_range(start, periods=len(rows), freq=freq, tz="UTC")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)


def flat_bars(n, price=1.1000):
    return make_bars([(price, price, price, price)] * n)


# --------------------------------------------------------------------------
# 1. Look-ahead
# --------------------------------------------------------------------------


class EnterOnce(Strategy):
    """Vstoupi presne jednou, kdyz je aktualni bar na indexu `at`.

    Index se odvozuje z delky viditelne historie, takze test mluvi primo
    v indexech baru a nemusi dopocitavat poradi volani.
    """

    warmup = 1

    def __init__(self, at=3, side="long", stop=1.0900, target=None):
        self.at, self.side, self.stop, self.target = at, side, stop, target
        self.seen_lengths = []

    def reset(self):
        self.seen_lengths = []

    def on_bar(self, ctx):
        self.seen_lengths.append(len(ctx.bars))
        bar_index = len(ctx.bars) - 1
        if bar_index == self.at and ctx.position is None:
            return Order(side=self.side, stop_loss=self.stop,
                         take_profit=self.target)
        return None


def test_strategie_nevidi_budouci_bary():
    """Historie v Contextu konci prave na aktualnim baru."""
    bars = make_bars([(1.1 + i * 0.001,) * 4 for i in range(20)])
    strat = EnterOnce(at=100)  # nikdy nevstoupi
    Backtest(bars, strat, ZERO_COST).run()

    # Prvni volani prijde na indexu warmup=1, tedy historie ma 2 radky.
    assert strat.seen_lengths[0] == 2
    # Kazde dalsi volani vidi presne o jeden bar vic.
    # Na poslednim baru uz se strategie nepta - nebylo by kam vyplnit,
    # takze nejdelsi videna historie je len(bars) - 1.
    assert strat.seen_lengths == list(range(2, len(bars)))
    assert max(strat.seen_lengths) < len(bars)


def test_vstup_se_plni_az_na_dalsim_otevreni():
    """Signal na baru i -> fill na open[i+1]. Ne na close[i]."""
    rows = [(1.1000, 1.1000, 1.1000, 1.1000)] * 4
    rows.append((1.2000, 1.2000, 1.2000, 1.2000))  # bar 4 ma jine open
    rows += [(1.2000, 1.2000, 1.2000, 1.2000)] * 6
    bars = make_bars(rows)

    strat = EnterOnce(at=3, stop=1.0000)
    res = Backtest(bars, strat, ZERO_COST).run()

    assert len(res.trades) == 1
    # Rozhodnuti padlo na baru 3 (close 1.1000), fill na open baru 4.
    assert res.trades[0].entry_price == pytest.approx(1.2000)
    assert res.trades[0].entry_time == bars.index[4]


def test_signal_na_poslednim_baru_se_neprovede():
    """Na posledni bar uz neni kam vyplnit - nesmi vzniknout obchod."""
    bars = flat_bars(10)
    strat = EnterOnce(at=9, stop=1.0900)
    res = Backtest(bars, strat, ZERO_COST).run()
    assert len(res.trades) == 0


# --------------------------------------------------------------------------
# 2. Vystupy - stop, target, gapy
# --------------------------------------------------------------------------


def test_stop_ma_prednost_pred_targetem_ve_stejnem_baru():
    """Kdyz bar obsahuje SL i TP, konzervativne se bere STOP."""
    rows = [(1.1000, 1.1000, 1.1000, 1.1000)] * 4
    rows.append((1.1000, 1.1000, 1.1000, 1.1000))          # fill zde
    rows.append((1.1000, 1.1200, 1.0800, 1.1000))          # zasahne obojí
    rows += [(1.1000, 1.1000, 1.1000, 1.1000)] * 4
    bars = make_bars(rows)

    strat = EnterOnce(at=3, stop=1.0900, target=1.1100)
    res = Backtest(bars, strat, ZERO_COST).run()

    assert len(res.trades) == 1
    t = res.trades[0]
    assert t.exit_reason == "stop"
    assert t.exit_price == pytest.approx(1.0900)
    assert t.net_pnl < 0


def test_gap_pres_stop_se_plni_na_otevreni():
    """Kdyz trh otevre pod stopem, plni se na open - ne na urovni stopu.

    Tohle je duvod, proc realny drawdown byva horsi nez v naivnim backtestu.
    """
    rows = [(1.1000, 1.1000, 1.1000, 1.1000)] * 5
    rows.append((1.0500, 1.0500, 1.0400, 1.0450))  # gap hluboko pod stop
    rows += [(1.0450, 1.0450, 1.0450, 1.0450)] * 4
    bars = make_bars(rows)

    strat = EnterOnce(at=3, stop=1.0900)
    res = Backtest(bars, strat, ZERO_COST).run()

    t = res.trades[0]
    assert t.exit_reason == "stop_gap"
    assert t.exit_price == pytest.approx(1.0500)  # ne 1.0900
    # Ztrata je vyrazne vetsi nez planovane riziko.
    assert abs(t.net_pnl) > t.risk_amount * 3


def test_target_se_plni_spravne():
    rows = [(1.1000, 1.1000, 1.1000, 1.1000)] * 5
    rows.append((1.1000, 1.1150, 1.1000, 1.1100))
    rows += [(1.1100, 1.1100, 1.1100, 1.1100)] * 4
    bars = make_bars(rows)

    strat = EnterOnce(at=3, stop=1.0900, target=1.1100)
    res = Backtest(bars, strat, ZERO_COST).run()

    t = res.trades[0]
    assert t.exit_reason == "target"
    assert t.exit_price == pytest.approx(1.1100)
    assert t.net_pnl > 0


# --------------------------------------------------------------------------
# 3. Velikost pozice a riziko
# --------------------------------------------------------------------------


def test_stop_znamena_presne_zadane_riziko():
    """Bez nakladu musi zasah stopu stat presne risk_per_trade z equity."""
    rows = [(1.1000, 1.1000, 1.1000, 1.1000)] * 5
    rows.append((1.1000, 1.1000, 1.0890, 1.0895))  # zasahne stop 1.0900
    rows += [(1.0895, 1.0895, 1.0895, 1.0895)] * 4
    bars = make_bars(rows)

    equity = 10_000.0
    risk = 0.005
    strat = EnterOnce(at=3, stop=1.0900)
    res = Backtest(bars, strat, ZERO_COST, initial_equity=equity,
                   risk_per_trade=risk).run()

    t = res.trades[0]
    assert t.net_pnl == pytest.approx(-equity * risk, rel=1e-9)
    assert t.r_multiple == pytest.approx(-1.0, rel=1e-9)


def test_prikaz_se_spatnou_stranou_stopu_je_odmitnut():
    """Long se stopem NAD vstupem nedava smysl - engine ho zahodi."""
    bars = flat_bars(12)
    strat = EnterOnce(at=3, side="long", stop=1.2000)
    res = Backtest(bars, strat, ZERO_COST).run()

    assert len(res.trades) == 0
    assert res.rejected_orders == 1


def test_paka_je_omezena():
    """Velmi tesny stop nesmi vyrobit pozici nad povoleny leverage."""
    bars = flat_bars(12)
    strat = EnterOnce(at=3, stop=1.09999)  # stop 0.1 pipu -> obri pozice
    res = Backtest(bars, strat, ZERO_COST, initial_equity=10_000.0,
                   max_leverage=30.0).run()

    assert len(res.trades) == 1
    notional = res.trades[0].units * res.trades[0].entry_price
    assert notional <= 10_000.0 * 30.0 * 1.0001


# --------------------------------------------------------------------------
# 4. Naklady
# --------------------------------------------------------------------------


def test_naklady_se_uctuji_a_snizuji_zisk():
    rows = [(1.1000, 1.1000, 1.1000, 1.1000)] * 5
    rows.append((1.1000, 1.1150, 1.1000, 1.1100))
    rows += [(1.1100, 1.1100, 1.1100, 1.1100)] * 4
    bars = make_bars(rows)

    costs = CostModel(spread_pips=1.0, slippage_pips=0.5,
                      commission_per_100k=7.0, swap_long_per_100k=0.0,
                      swap_short_per_100k=0.0)
    strat = EnterOnce(at=3, stop=1.0900, target=1.1100)
    res = Backtest(bars, strat, costs).run()

    t = res.trades[0]
    units = t.units
    expected = (1.0 * 1e-4 * units) + (2 * 0.5 * 1e-4 * units) + (7.0 * units / 1e5)
    assert t.costs == pytest.approx(expected, rel=1e-9)
    assert t.net_pnl == pytest.approx(t.gross_pnl - t.costs, rel=1e-9)
    assert t.net_pnl < t.gross_pnl


def test_swap_se_uctuje_za_drzeni_pres_rollover():
    """Pozice drzena pres 21:00 UTC musi zaplatit swap."""
    # Zacneme ve 12:00, drzime pres 21:00 -> jeden rollover.
    rows = [(1.1000, 1.1000, 1.1000, 1.1000)] * 20
    bars = make_bars(rows, start="2024-01-02 12:00")

    costs = CostModel(spread_pips=0.0, slippage_pips=0.0,
                      commission_per_100k=0.0, swap_long_per_100k=-10.0,
                      swap_short_per_100k=0.0, triple_swap_weekday=99)
    strat = EnterOnce(at=1, stop=1.0900)
    res = Backtest(bars, strat, costs).run()

    t = res.trades[0]
    assert t.swap > 0  # kladne = naklad
    nights = t.swap / (10.0 * t.units / 1e5)
    assert nights == pytest.approx(round(nights), abs=1e-6)
    assert nights >= 1


# --------------------------------------------------------------------------
# 5. Validace vstupu
# --------------------------------------------------------------------------


def test_neserazena_data_jsou_odmitnuta():
    bars = flat_bars(10)
    shuffled = bars.iloc[[3, 1, 2, 0] + list(range(4, 10))]
    with pytest.raises(ValueError, match="serazene"):
        Backtest(shuffled, EnterOnce(), ZERO_COST)


def test_nekonzistentni_ohlc_je_odmitnuto():
    bars = flat_bars(10).copy()
    bars.iloc[5, bars.columns.get_loc("high")] = 1.0500  # high pod low
    with pytest.raises(ValueError, match="Nekonzistentni"):
        Backtest(bars, EnterOnce(), ZERO_COST)


def test_duplicitni_timestampy_jsou_odmitnuty():
    bars = flat_bars(10)
    dup = pd.concat([bars, bars.iloc[[5]]]).sort_index()
    with pytest.raises(ValueError, match="[Dd]uplicit"):
        Backtest(dup, EnterOnce(), ZERO_COST)


# --------------------------------------------------------------------------
# 6. Equity krivka
# --------------------------------------------------------------------------


def test_equity_krivka_sedi_na_soucet_obchodu():
    rows = [(1.1000, 1.1000, 1.1000, 1.1000)] * 5
    rows.append((1.1000, 1.1150, 1.1000, 1.1100))
    rows += [(1.1100, 1.1100, 1.1100, 1.1100)] * 6
    bars = make_bars(rows)

    strat = EnterOnce(at=3, stop=1.0900, target=1.1100)
    res = Backtest(bars, strat, ZERO_COST, initial_equity=10_000.0).run()

    total = sum(t.net_pnl for t in res.trades)
    assert res.equity_curve.iloc[-1] == pytest.approx(10_000.0 + total, rel=1e-9)


def test_bez_obchodu_zustava_equity_konstantni():
    bars = flat_bars(30)
    strat = EnterOnce(at=999)
    res = Backtest(bars, strat, ZERO_COST, initial_equity=10_000.0).run()

    assert len(res.trades) == 0
    assert (res.equity_curve == 10_000.0).all()
