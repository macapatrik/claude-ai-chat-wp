#!/usr/bin/env python3
"""Spusti ziveho bota.

TRI REZIMY, OD NEJBEZPECNEJSIHO
-------------------------------
1. --dry-run (vychozi)
   Bere ziva data z OANDA, pocita signaly, ale ZADNY prikaz neposila.
   Do zurnalu zapisuje, co by udelal. Tady zacni a nech to bezet tyden.

       python3 scripts/run_bot.py --strategy london --dry-run

2. --paper
   Obchoduje proti simulovanemu brokerovi v pameti, na zivych cenach.
   Overi celou smycku vcetne evidence pozic.

       python3 scripts/run_bot.py --strategy london --paper

3. --live
   Skutecne prikazy na skutecnem uctu. Vyzaduje potvrzeni napsanim
   "ROZUMIM RIZIKU". Bez --real-money mirí na DEMO ucet.

       export OANDA_TOKEN="..."
       export OANDA_ACCOUNT="101-004-1234567-001"
       python3 scripts/run_bot.py --strategy london --live

PRED PRVNIM ZIVYM SPUSTENIM
---------------------------
Pust backtest te same strategie na realnych datech. Kdyz nema kladnou
expectancy po nakladech, ziva verze ti jen rychleji vezme penize.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fxlab.data import pip_size_for
from fxlab.strategies import AsiaReversion, DonchianBreakout, LondonBreakout
from fxlive import (
    Journal, OandaBroker, PaperBroker, RiskLimits, RiskManager,
    Runner, RunnerConfig, StateStore,
)

STRATEGIES = {
    "london": LondonBreakout,
    "asia": AsiaReversion,
    "donchian": DonchianBreakout,
}

CONFIRM = "ROZUMIM RIZIKU"


def setup_logging(verbose: bool, logfile: Path) -> None:
    logfile.parent.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s  %(levelname)-7s %(name)-16s %(message)s"
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format=fmt,
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(logfile, encoding="utf-8")],
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--strategy", choices=list(STRATEGIES), default="london")
    p.add_argument("--instrument", default="EUR_USD")
    p.add_argument("--granularity", default="H1",
                   choices=["M5", "M15", "M30", "H1", "H4"])

    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True,
                      help="Ziva data, zadne prikazy (vychozi)")
    mode.add_argument("--paper", action="store_true",
                      help="Simulovany broker na zivych cenach")
    mode.add_argument("--live", action="store_true",
                      help="Skutecne prikazy")

    p.add_argument("--real-money", action="store_true",
                   help="S --live miri na OSTRY ucet misto dema")
    p.add_argument("--resume", action="store_true",
                   help="Zrusi ulozeny HALT a pokracuje")

    p.add_argument("--risk", type=float, default=0.005,
                   help="Podil equity na obchod (0.005 = 0.5 %%)")
    p.add_argument("--max-daily-loss", type=float, default=0.02)
    p.add_argument("--max-drawdown", type=float, default=0.15)
    p.add_argument("--max-trades-per-day", type=int, default=10)

    p.add_argument("--state-dir", default="data/live")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    state_dir = Path(args.state_dir)
    tag = f"{args.instrument}_{args.strategy}_{args.granularity}"
    setup_logging(args.verbose, state_dir / f"{tag}.log")
    log = logging.getLogger("run_bot")

    pip = pip_size_for(args.instrument.replace("_", ""))

    # -- broker -----------------------------------------------------------

    token = os.environ.get("OANDA_TOKEN", "")
    account_id = os.environ.get("OANDA_ACCOUNT", "")

    if args.live:
        if not token or not account_id:
            log.error(
                "Zivy rezim potrebuje OANDA_TOKEN a OANDA_ACCOUNT "
                "v promennych prostredi."
            )
            return 2

        target = "OSTRY UCET SE SKUTECNYMI PENEZI" if args.real_money else "DEMO ucet"
        print()
        print("=" * 68)
        print(f"  ZIVY REZIM -> {target}")
        print(f"  Ucet:       {account_id}")
        print(f"  Instrument: {args.instrument} {args.granularity}")
        print(f"  Strategie:  {args.strategy}")
        print(f"  Riziko:     {args.risk:.2%} na obchod, "
              f"denni strop ztraty {args.max_daily_loss:.1%}")
        print("=" * 68)
        if args.real_money:
            print("  Muzes prijit o vsechny prostredky na tomto uctu.")
            print(f'  Pro pokracovani napis: {CONFIRM}')
            if input("  > ").strip() != CONFIRM:
                print("  Zruseno.")
                return 1
        print()

        broker = OandaBroker(token, account_id, practice=not args.real_money)
        data_broker = broker

    elif args.paper:
        if not token or not account_id:
            log.error("I paper rezim potrebuje OANDA_TOKEN a OANDA_ACCOUNT "
                      "kvuli zivym datum.")
            return 2
        data_broker = OandaBroker(token, account_id, practice=True)
        broker = PaperBroker(balance=10_000.0, pip=pip)
        # Papirovy broker potrebuje aktualni cenu pro ocenovani pozic.
        broker._price_source = lambda inst: float(
            data_broker.candles(inst, args.granularity, 1)["close"].iloc[-1]
        )
        log.info("PAPER: simulovany ucet 10 000 USD na zivych cenach.")

    else:
        if not token or not account_id:
            log.error("Dry-run potrebuje OANDA_TOKEN a OANDA_ACCOUNT "
                      "kvuli zivym datum. Ucet zustane nedotcen.")
            return 2
        broker = OandaBroker(token, account_id, practice=True)
        data_broker = broker
        log.info("DRY-RUN: zadny prikaz nebude odeslan.")

    # -- slozeni ----------------------------------------------------------

    limits = RiskLimits(
        risk_per_trade=args.risk,
        max_daily_loss=args.max_daily_loss,
        max_total_drawdown=args.max_drawdown,
        max_trades_per_day=args.max_trades_per_day,
    )
    risk = RiskManager(limits, pip=pip)

    store = StateStore(state_dir / f"{tag}.state.json")
    journal = Journal(state_dir / f"{tag}.journal.sqlite")

    strategy = STRATEGIES[args.strategy]()
    if hasattr(strategy, "pip"):
        strategy.pip = pip

    cfg = RunnerConfig(
        instrument=args.instrument,
        granularity=args.granularity,
        dry_run=not (args.live or args.paper),
        pip=pip,
    )

    runner = Runner(cfg, broker, strategy, risk, store, journal,
                    data_broker=data_broker)

    if args.resume and runner.risk.state.halted:
        log.warning("Ruším halt na prani uzivatele: %s",
                    runner.risk.state.halt_reason)
        runner.risk.resume()
        runner.state.risk = runner.risk.state
        store.save(runner.state)

    try:
        runner.run_forever()
    finally:
        journal.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
