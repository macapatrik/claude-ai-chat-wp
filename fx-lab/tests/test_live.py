"""Testy zive vrstvy.

Zivy bot nejde otestovat proti skutecnemu brokerovi, aniz bys riskoval
penize. Testuje se proti `PaperBroker` a proti falesnym brokerum, kteri
umyslne selhavaji.

Kazdy test tu odpovida jednomu zpusobu, jak zivy bot prijde o penize:
dvojity vstup po restartu, zdvojeny prikaz po vypadku site, ignorovany
limit ztraty, obchod pri zavrenem trhu, sizing utrzeny ze retezu.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fxlab.engine import Close, Context, Order
from fxlab.strategies.base import Strategy
from fxlive.broker import BrokerPosition, PaperBroker
from fxlive.risk import Rejected, RiskLimits, RiskManager, RiskState
from fxlive.runner import Runner, RunnerConfig
from fxlive.state import BotState, Journal, StateStore

UTC = dt.timezone.utc


# --------------------------------------------------------------------------
# pomocne
# --------------------------------------------------------------------------


def bars(n=60, price=1.1000, start="2024-06-03 00:00"):
    idx = pd.date_range(start, periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {"open": price, "high": price + 0.0005, "low": price - 0.0005,
         "close": price},
        index=idx,
    )


class FakeDataBroker:
    """Vraci predem dane bary. Meni se mezi cykly."""

    def __init__(self, frames):
        self._frames = list(frames)
        self.calls = 0

    def candles(self, instrument, granularity, count):
        f = self._frames[min(self.calls, len(self._frames) - 1)]
        self.calls += 1
        return f


class OnceStrategy(Strategy):
    """Vstoupi pri prvnim volani, pak uz nic."""

    warmup = 1

    def __init__(self, side="long", stop=1.0950, target=1.1100):
        self.side, self.stop, self.target = side, stop, target
        self.calls = 0
        self.seen_positions = []

    def on_bar(self, ctx):
        self.calls += 1
        self.seen_positions.append(ctx.position)
        if self.calls == 1 and ctx.position is None:
            return Order(side=self.side, stop_loss=self.stop,
                         take_profit=self.target)
        return None


class CloserStrategy(Strategy):
    warmup = 1

    def on_bar(self, ctx):
        return Close("test") if ctx.position is not None else None


class NoopStrategy(Strategy):
    """Nikdy nic nenavrhne. Na testy, kde jde o samotnou smycku."""

    warmup = 1

    def on_bar(self, ctx):
        return None


def make_runner(tmp_path, strategy, broker, data_broker=None, limits=None,
                dry_run=False, state=None):
    store = StateStore(tmp_path / "s.json")
    if state is not None:
        store.save(state)
    journal = Journal(tmp_path / "j.sqlite")
    risk = RiskManager(limits or RiskLimits())
    cfg = RunnerConfig(instrument="EUR_USD", granularity="H1", dry_run=dry_run)
    return Runner(cfg, broker, strategy, risk, store, journal,
                  data_broker=data_broker or FakeDataBroker([bars()]))


# --------------------------------------------------------------------------
# 1. Rizikova vrstva
# --------------------------------------------------------------------------


def test_sizing_odpovida_zadanemu_riziku():
    rm = RiskManager(RiskLimits(risk_per_trade=0.01))
    units = rm.size_position(equity=10_000, entry_price=1.1000, stop_loss=1.0900)
    # stop 100 pipu = 0.01 ceny; riziko 100 USD -> 10 000 jednotek
    assert units == pytest.approx(10_000.0)
    assert units * 0.01 == pytest.approx(100.0)


def test_prilis_tesny_stop_je_odmitnut():
    rm = RiskManager(RiskLimits(min_stop_distance_pips=3.0))
    with pytest.raises(Rejected, match="tesny"):
        rm.size_position(10_000, 1.1000, 1.09995)   # 0.5 pipu


def test_prilis_siroky_stop_je_odmitnut():
    rm = RiskManager(RiskLimits(max_stop_distance_pips=200.0))
    with pytest.raises(Rejected, match="siroky"):
        rm.size_position(10_000, 1.1000, 1.0500)    # 500 pipu


def test_paka_je_omezena():
    """Velke riziko na obchod nesmi protlacit pozici pres ESMA limit."""
    rm = RiskManager(RiskLimits(risk_per_trade=0.5, max_leverage=30.0))
    units = rm.size_position(10_000, 1.1000, 1.0995)   # 5 pipu, platny stop
    # bez stropu by vyslo 10 000 000 jednotek
    assert units * 1.1000 <= 10_000 * 30 * 1.0001


def test_absolutni_strop_velikosti():
    rm = RiskManager(RiskLimits(risk_per_trade=0.9, max_leverage=1e9,
                                max_position_units=50_000))
    units = rm.size_position(1_000_000, 1.1000, 1.0995)
    assert units <= 50_000


def test_stop_na_spatne_strane_je_odmitnut():
    rm = RiskManager(RiskLimits())
    with pytest.raises(Rejected, match="long"):
        rm.validate_order("long", 1.1000, 1.1100, None)
    with pytest.raises(Rejected, match="short"):
        rm.validate_order("short", 1.1000, 1.0900, None)


def test_denni_limit_ztraty_vypne_bota():
    rm = RiskManager(RiskLimits(max_daily_loss=0.02))
    now = dt.datetime(2024, 6, 3, 10, tzinfo=UTC)
    rm.roll_day(now, 10_000)

    assert rm.check_halt(9_900) is None          # 1 % ztrata, jeste ok
    reason = rm.check_halt(9_800)                # 2 % ztrata
    assert reason and "denni" in reason
    assert rm.state.halted
    assert rm.can_open(now, 9_800) is not None


def test_celkovy_drawdown_vypne_bota():
    rm = RiskManager(RiskLimits(max_total_drawdown=0.15, max_daily_loss=0.99))
    now = dt.datetime(2024, 6, 3, 10, tzinfo=UTC)
    rm.roll_day(now, 12_000)
    rm.update_equity(12_000)

    assert rm.check_halt(11_000) is None
    reason = rm.check_halt(10_100)               # -15.8 % od vrcholu
    assert reason and "drawdown" in reason


def test_novy_den_rusi_denni_halt_ale_ne_drawdown():
    rm = RiskManager(RiskLimits(max_daily_loss=0.02))
    d1 = dt.datetime(2024, 6, 3, 10, tzinfo=UTC)
    rm.roll_day(d1, 10_000)
    rm.check_halt(9_700)
    assert rm.state.halted

    d2 = dt.datetime(2024, 6, 4, 10, tzinfo=UTC)
    rm.roll_day(d2, 9_700)
    assert not rm.state.halted

    rm._halt("celkovy drawdown 20 %")
    rm.roll_day(dt.datetime(2024, 6, 5, 10, tzinfo=UTC), 9_700)
    assert rm.state.halted   # drawdown halt prezije novy den


def test_vikend_blokuje_vstup():
    rm = RiskManager(RiskLimits())
    rm.roll_day(dt.datetime(2024, 6, 8, 12, tzinfo=UTC), 10_000)
    # sobota
    assert "zavreny" in rm.can_open(dt.datetime(2024, 6, 8, 12, tzinfo=UTC), 10_000)
    # patek po 21:00
    assert "zavreny" in rm.can_open(dt.datetime(2024, 6, 7, 22, tzinfo=UTC), 10_000)
    # streda v poledne
    assert rm.can_open(dt.datetime(2024, 6, 5, 12, tzinfo=UTC), 10_000) is None


def test_denni_limit_poctu_obchodu():
    rm = RiskManager(RiskLimits(max_trades_per_day=2))
    now = dt.datetime(2024, 6, 5, 12, tzinfo=UTC)
    rm.roll_day(now, 10_000)

    assert rm.can_open(now, 10_000) is None
    rm.record_fill(opened=True)
    rm.record_fill(opened=True)
    assert "limit obchodu" in rm.can_open(now, 10_000)


# --------------------------------------------------------------------------
# 2. Idempotence prikazu
# --------------------------------------------------------------------------


def test_stejny_client_id_neotevre_druhou_pozici():
    """Vypadek site mezi odeslanim a odpovedi nesmi zdvojit pozici."""
    b = PaperBroker(balance=10_000)
    b.set_price("EUR_USD", 1.1000)

    r1 = b.market_order("EUR_USD", "long", 10_000, 1.0900, 1.1100, "cid-1")
    assert r1.accepted and not r1.duplicate

    r2 = b.market_order("EUR_USD", "long", 10_000, 1.0900, 1.1100, "cid-1")
    assert r2.duplicate
    assert r2.trade_id == r1.trade_id
    assert b.account().open_position_count == 1


def test_druhy_vstup_bez_zavreni_je_odmitnut():
    b = PaperBroker(balance=10_000)
    b.set_price("EUR_USD", 1.1000)
    b.market_order("EUR_USD", "long", 10_000, 1.0900, None, "cid-1")

    r = b.market_order("EUR_USD", "long", 10_000, 1.0900, None, "cid-2")
    assert not r.accepted
    assert "otevrena" in r.reason


# --------------------------------------------------------------------------
# 3. Stav a reconcile
# --------------------------------------------------------------------------


def test_stav_prezije_zapis_a_nacteni(tmp_path):
    store = StateStore(tmp_path / "s.json")
    st = BotState(last_bar_time="2024-06-03T10:00:00+00:00",
                  open_trade_id="t-1", strategy_name="LondonBreakout")
    st.risk = RiskState(day="2024-06-03", day_start_equity=10_000,
                        trades_today=3, peak_equity=10_500)
    store.save(st)

    back = StateStore(tmp_path / "s.json").load()
    assert back.last_bar_time == st.last_bar_time
    assert back.open_trade_id == "t-1"
    assert back.risk.trades_today == 3
    assert back.risk.peak_equity == 10_500


def test_poskozeny_stav_se_odlozi_a_zacne_se_znovu(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{tohle neni platny json")
    st = StateStore(p).load()

    assert st.last_bar_time == ""
    assert p.with_suffix(".corrupt").exists()


def test_reconcile_prebira_pozici_o_ktere_bot_nevedel(tmp_path):
    """Po restartu se veri BROKEROVI, ne ulozenemu stavu."""
    b = PaperBroker(balance=10_000)
    b.set_price("EUR_USD", 1.1000)
    b.market_order("EUR_USD", "long", 10_000, 1.0900, None, "existing")

    runner = make_runner(tmp_path, OnceStrategy(), b, state=BotState())
    pos = runner.reconcile()

    assert pos is not None and pos.side == "long"
    assert runner.state.open_trade_id == pos.trade_id


def test_reconcile_zapomene_pozici_ktera_uz_neexistuje(tmp_path):
    b = PaperBroker(balance=10_000)
    b.set_price("EUR_USD", 1.1000)

    stale = BotState(open_trade_id="uz-neexistuje")
    runner = make_runner(tmp_path, OnceStrategy(), b, state=stale)
    pos = runner.reconcile()

    assert pos is None
    assert runner.state.open_trade_id == ""


def test_reconcile_dohleda_nevyrizeny_prikaz(tmp_path):
    b = PaperBroker(balance=10_000)
    b.set_price("EUR_USD", 1.1000)
    b.market_order("EUR_USD", "long", 10_000, 1.0900, None, "pending-1")

    st = BotState(pending_client_id="pending-1")
    runner = make_runner(tmp_path, OnceStrategy(), b, state=st)
    runner.reconcile()

    assert runner.state.pending_client_id == ""
    assert runner.state.open_trade_id is not None

    events = runner.journal.recent(kind="reconcile_pending")
    assert len(events) == 1
    assert json.loads(events[0]["detail"])["position_found"] is True


# --------------------------------------------------------------------------
# 4. Smycka
# --------------------------------------------------------------------------


def test_stejna_svicka_se_nezpracuje_dvakrat(tmp_path):
    """Jinak by kazdy cyklus poslal dalsi prikaz."""
    b = PaperBroker(balance=10_000)
    b.set_price("EUR_USD", 1.1000)
    strat = OnceStrategy()
    same = bars()
    runner = make_runner(tmp_path, strat, b,
                         data_broker=FakeDataBroker([same, same, same]))
    runner.reconcile()

    runner.step()
    runner.step()
    runner.step()

    assert strat.calls == 1
    assert b.account().open_position_count == 1


def test_signal_otevre_pozici_pres_celou_smycku(tmp_path):
    b = PaperBroker(balance=10_000)
    b.set_price("EUR_USD", 1.1000)
    runner = make_runner(tmp_path, OnceStrategy(stop=1.0950), b)
    runner.reconcile()
    runner.step()

    pos = b.position("EUR_USD")
    assert pos is not None and pos.side == "long"
    assert pos.stop_loss == pytest.approx(1.0950)
    # 0.5 % z 10 000 = 50 USD rizika pri stopu 50 pipu -> 10 000 jednotek
    assert pos.units == pytest.approx(10_000, rel=0.02)

    assert len(runner.journal.recent(kind="open")) == 1


def test_dry_run_neposle_zadny_prikaz(tmp_path):
    b = PaperBroker(balance=10_000)
    b.set_price("EUR_USD", 1.1000)
    runner = make_runner(tmp_path, OnceStrategy(), b, dry_run=True)
    runner.reconcile()
    runner.step()

    assert b.account().open_position_count == 0
    assert len(runner.journal.recent(kind="dry_open")) == 1
    assert len(runner.journal.recent(kind="open")) == 0


def test_strategie_vidi_pozici_z_brokera(tmp_path):
    """Strategie nesmi poznat rozdil mezi backtestem a zivym behem."""
    b = PaperBroker(balance=10_000)
    b.set_price("EUR_USD", 1.1000)
    b.market_order("EUR_USD", "long", 10_000, 1.0900, 1.1100, "pre")

    strat = OnceStrategy()
    f1, f2 = bars(60), bars(61)
    runner = make_runner(tmp_path, strat, b, data_broker=FakeDataBroker([f1, f2]))
    runner.reconcile()
    runner.step()

    seen = strat.seen_positions[0]
    assert seen is not None
    assert seen.side == "long"
    assert seen.stop_loss == pytest.approx(1.0900)
    assert seen.take_profit == pytest.approx(1.1100)


def test_close_signal_zavre_pozici(tmp_path):
    b = PaperBroker(balance=10_000)
    b.set_price("EUR_USD", 1.1000)
    b.market_order("EUR_USD", "long", 10_000, 1.0900, None, "pre")

    runner = make_runner(tmp_path, CloserStrategy(), b)
    runner.reconcile()
    runner.step()

    assert b.position("EUR_USD") is None
    assert len(runner.journal.recent(kind="close")) == 1


def test_halt_zastavi_obchodovani(tmp_path):
    b = PaperBroker(balance=10_000)
    b.set_price("EUR_USD", 1.1000)
    limits = RiskLimits(max_daily_loss=0.001)   # 0.1 %, okamzity halt
    strat = OnceStrategy()
    runner = make_runner(tmp_path, strat, b, limits=limits)
    runner.reconcile()

    # Umely propad equity pod denni limit
    runner.risk.state.day_start_equity = 20_000
    runner.step()

    assert runner.risk.state.halted
    assert b.account().open_position_count == 0
    assert len(runner.journal.recent(kind="halt")) == 1


def test_zamitnuty_prikaz_neotevre_pozici(tmp_path):
    """Stop 1 pip pod vstupem musi rizikova vrstva odmitnout."""
    b = PaperBroker(balance=10_000)
    b.set_price("EUR_USD", 1.1000)
    strat = OnceStrategy(stop=1.09995)          # 0.5 pipu
    runner = make_runner(tmp_path, strat, b)
    runner.reconcile()
    runner.step()

    assert b.account().open_position_count == 0
    rejected = runner.journal.recent(kind="rejected")
    assert len(rejected) == 1
    assert "tesny" in rejected[0]["detail"]


def test_zavreni_stopem_se_pozna(tmp_path):
    b = PaperBroker(balance=10_000)
    b.set_price("EUR_USD", 1.1000)
    b.market_order("EUR_USD", "long", 10_000, 1.0900, None, "pre")

    f1, f2 = bars(60), bars(61)
    # NoopStrategy, aby po zavreni hned neotevrela dalsi pozici a nezamlzila,
    # co se testuje.
    runner = make_runner(tmp_path, NoopStrategy(), b,
                         data_broker=FakeDataBroker([f1, f2]))
    runner.reconcile()
    assert runner.state.open_trade_id

    # Trh spadne, stop se trefi u brokera
    b.set_price("EUR_USD", 1.0850)
    assert b.trigger_stops("EUR_USD", high=1.0950, low=1.0850) == "stop"

    runner.step()

    assert runner.state.open_trade_id == ""
    assert len(runner.journal.recent(kind="closed_by_broker")) == 1


class MaxBarsStrategy(Strategy):
    """Vstoupi jednou s vynucenym zavrenim po 3 barech."""

    warmup = 1

    def __init__(self):
        self.calls = 0

    def on_bar(self, ctx):
        self.calls += 1
        if self.calls == 1 and ctx.position is None:
            return Order(side="long", stop_loss=1.0950, max_bars=3)
        return None


def test_max_bars_zavre_pozici_i_zive(tmp_path):
    """Regrese: strategie s max_bars musi zive zavirat stejne jako v backtestu.

    Backtest to resi ve smycce enginu. Runner to musel dostat taky, jinak
    by pozice zustala viset az do stopu.
    """
    b = PaperBroker(balance=10_000)
    b.set_price("EUR_USD", 1.1000)
    frames = [bars(60 + k) for k in range(6)]
    strat = MaxBarsStrategy()
    runner = make_runner(tmp_path, strat, b, data_broker=FakeDataBroker(frames))
    runner.reconcile()

    runner.step()                                    # otevre
    assert b.account().open_position_count == 1
    assert runner.state.open_max_bars == 3

    runner.step(); runner.step()                     # bars_held 1, 2
    assert b.account().open_position_count == 1

    runner.step()                                    # bars_held 3 -> zavrit
    assert b.account().open_position_count == 0

    closes = runner.journal.recent(kind="close")
    assert len(closes) == 1
    assert closes[0]["detail"] == "max_bars"
    assert runner.state.open_max_bars == 0


def test_bars_held_prezije_restart(tmp_path):
    """Po restartu se nesmi pocitadlo baru vynulovat - jinak by pozice
    zustala otevrena o N baru dele."""
    store = StateStore(tmp_path / "s.json")
    st = BotState(open_trade_id="t-9", open_bars_held=2, open_max_bars=3)
    store.save(st)

    back = StateStore(tmp_path / "s.json").load()
    assert back.open_bars_held == 2
    assert back.open_max_bars == 3


def test_paper_broker_trefi_stop_ve_smycce(tmp_path):
    """Regrese: v --paper rezimu musi pozice trefit stop.

    PaperBroker si SL/TP nehlida sam. Driv to volal jen replay skript,
    takze v zivem paper rezimu se pozice drzela donekonecna.
    """
    b = PaperBroker(balance=10_000, spread_pips=0.0)
    b.set_price("EUR_USD", 1.1000)
    b.market_order("EUR_USD", "long", 10_000, 1.0950, None, "pre")
    assert b.account().open_position_count == 1

    # Bar, jehoz low sahne pod stop.
    idx = pd.date_range("2024-06-05 00:00", periods=60, freq="1h", tz="UTC")
    drop = pd.DataFrame(
        {"open": 1.1000, "high": 1.1000, "low": 1.0900, "close": 1.0920},
        index=idx,
    )

    runner = make_runner(tmp_path, NoopStrategy(), b,
                         data_broker=FakeDataBroker([drop]))
    runner.reconcile()
    runner.step()

    assert b.account().open_position_count == 0
    assert any(f.get("reason") == "stop" for f in b.fills)


def test_stop_nevykopne_pozici_otevrenou_na_stejnem_baru(tmp_path):
    """Pohyb, ktery probehl PRED vstupem, nesmi pozici zavrit.

    Proto se SL/TP kontroluji driv, nez bar uvidi strategie.
    """
    b = PaperBroker(balance=10_000, spread_pips=0.0)
    b.set_price("EUR_USD", 1.1000)

    idx = pd.date_range("2024-06-05 00:00", periods=60, freq="1h", tz="UTC")
    # Bar ma hluboke low, ale pozice na nem teprve vznikne.
    frame = pd.DataFrame(
        {"open": 1.1000, "high": 1.1010, "low": 1.0900, "close": 1.1000},
        index=idx,
    )

    runner = make_runner(tmp_path, OnceStrategy(stop=1.0950), b,
                         data_broker=FakeDataBroker([frame]))
    runner.reconcile()
    runner.step()

    # Pozice musi byt otevrena - low 1.0900 nastalo pred vstupem.
    assert b.account().open_position_count == 1


def test_zurnal_zaznamena_kazdy_bar(tmp_path):
    b = PaperBroker(balance=10_000)
    b.set_price("EUR_USD", 1.1000)
    runner = make_runner(tmp_path, OnceStrategy(), b,
                         data_broker=FakeDataBroker([bars(60), bars(61), bars(62)]))
    runner.reconcile()
    runner.step()
    runner.step()
    runner.step()

    assert len(runner.journal.recent(kind="bar", limit=10)) == 3
