#!/usr/bin/env python3
"""Preflight: overi napojeni na OANDA driv, nez pustis bota.

PROC TENHLE SKRIPT EXISTUJE
---------------------------
Napojeni na OANDA bylo napsane bez moznosti ho vyzkouset - prostredi, kde
kod vznikal, nema pristup na brokerske hosty. Kazdy pozadavek a kazde cteni
odpovedi je tedy napsane podle dokumentace, ne overene proti realu.

Tenhle skript projde vsechny cesty, ktere bot pouziva, a rekne u kazde,
jestli sedi. Kdyz nekde vypise FAIL, ukaze i skutecny tvar odpovedi, aby
slo rychle najit, co je jinak.

Pust ho driv nez `run_bot.py`. Trva par sekund.

    export OANDA_TOKEN="..."
    export OANDA_ACCOUNT="101-004-1234567-001"
    python3 scripts/check_oanda.py

Volitelne overi i odesilani prikazu. Otevre pozici o velikosti 1 jednotky
(radove setiny centu rizika) a hned ji zavre. Jen na DEMO uctu:

    python3 scripts/check_oanda.py --with-order-test
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fxlive.broker import BrokerError, OandaBroker, TransientError

OK = "  OK  "
FAIL = " FAIL "
WARN = " WARN "
SKIP = " SKIP "

results: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))
    line = f"[{status}] {name}"
    if detail:
        line += f"\n         {detail}"
    print(line)


def show_shape(obj, depth: int = 0, limit: int = 14) -> str:
    """Vypise klice odpovedi, aby slo poznat, co je jinak nez cekame."""
    if isinstance(obj, dict):
        keys = list(obj)[:limit]
        return "{" + ", ".join(keys) + ("..." if len(obj) > limit else "") + "}"
    if isinstance(obj, list):
        return f"[{len(obj)} polozek]" + (
            " prvni: " + show_shape(obj[0]) if obj else ""
        )
    return type(obj).__name__


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--instrument", default="EUR_USD")
    p.add_argument("--granularity", default="H1")
    p.add_argument("--with-order-test", action="store_true",
                   help="Otevre a hned zavre pozici o 1 jednotce (jen demo)")
    p.add_argument("--real-money", action="store_true",
                   help="Mirit na ostry ucet misto dema (jen cteni)")
    args = p.parse_args()

    token = os.environ.get("OANDA_TOKEN", "")
    account_id = os.environ.get("OANDA_ACCOUNT", "")

    print("=" * 66)
    print("  Preflight OANDA")
    print("=" * 66)

    # -- 0. promenne prostredi -------------------------------------------

    if not token:
        record(FAIL, "OANDA_TOKEN", "chybi promenna prostredi")
        print("\nToken vygenerujes v uctu: Manage API Access -> Generate.")
        return 2
    record(OK, "OANDA_TOKEN", f"nacten ({len(token)} znaku)")

    if not account_id:
        record(FAIL, "OANDA_ACCOUNT", "chybi promenna prostredi")
        print("\nID uctu najdes v prehledu, tvar 101-004-1234567-001.")
        return 2
    record(OK, "OANDA_ACCOUNT", account_id)

    if args.with_order_test and args.real_money:
        record(FAIL, "bezpecnost",
               "--with-order-test na ostrem uctu je zakazan")
        return 2

    practice = not args.real_money
    print(f"\nCil: {'DEMO (api-fxpractice)' if practice else 'OSTRY (api-fxtrade)'}\n")

    broker = OandaBroker(token, account_id, practice=practice)

    # -- 1. autentizace a shrnuti uctu -----------------------------------

    try:
        acct = broker.account()
    except BrokerError as e:
        msg = str(e)
        if "401" in msg:
            record(FAIL, "autentizace",
                   "HTTP 401 - token je neplatny, nebo mirí na jine prostredi. "
                   "Demo token nefunguje na ostrem uctu a naopak.")
        elif "404" in msg:
            record(FAIL, "shrnuti uctu",
                   f"HTTP 404 - ucet {account_id} na tomhle prostredi neexistuje.")
        else:
            record(FAIL, "shrnuti uctu", msg[:300])
        return 1
    except TransientError as e:
        record(FAIL, "sit", str(e)[:300])
        return 1

    record(OK, "autentizace", "token prijat")
    record(OK, "shrnuti uctu",
           f"zustatek {acct.balance:,.2f} {acct.currency}, "
           f"equity {acct.equity:,.2f}, otevrenych pozic {acct.open_position_count}")

    if acct.currency != "USD":
        record(WARN, "mena uctu",
               f"ucet je v {acct.currency}. Vypocet velikosti pozice "
               f"predpoklada USD ucet a USD-kotovany par. "
               f"Na {acct.currency} uctu bude sizing nespravny.")

    if acct.balance <= 0:
        record(WARN, "zustatek", "nulovy zustatek - bot nebude moct obchodovat")

    # -- 2. svicky -------------------------------------------------------

    try:
        bars = broker.candles(args.instrument, args.granularity, 60)
    except (BrokerError, TransientError) as e:
        record(FAIL, "svicky", str(e)[:300])
        return 1

    missing = [c for c in ("open", "high", "low", "close") if c not in bars.columns]
    if missing:
        record(FAIL, "tvar svicek", f"chybi sloupce {missing}, mame {list(bars.columns)}")
        return 1

    record(OK, "svicky",
           f"{len(bars)} dokoncenych, posledni {bars.index[-1]} "
           f"close {bars['close'].iloc[-1]:.5f}")

    if not str(bars.index.tz) in ("UTC", "utc"):
        record(WARN, "casova zona svicek",
               f"index neni v UTC ({bars.index.tz}) - obchodni okna by sedela spatne")
    else:
        record(OK, "casova zona svicek", "UTC")

    bad = bars[(bars.high < bars.low) | (bars.high < bars.close)]
    if len(bad):
        record(FAIL, "konzistence OHLC", f"{len(bad)} vadnych baru")
    else:
        record(OK, "konzistence OHLC", "high/low/close sedi na vsech barech")

    if len(bars) < 50:
        record(WARN, "delka historie",
               f"jen {len(bars)} baru - strategie potrebuji 50+ na warmup")

    # -- 3. dotaz na pozici ----------------------------------------------

    try:
        pos = broker.position(args.instrument)
    except (BrokerError, TransientError) as e:
        record(FAIL, "dotaz na pozici", str(e)[:300])
        return 1

    if pos is None:
        record(OK, "dotaz na pozici", f"zadna otevrena pozice na {args.instrument}")
    else:
        record(OK, "dotaz na pozici",
               f"{pos.side} {pos.units:.0f} @ {pos.entry_price:.5f}, "
               f"SL {pos.stop_loss}, TP {pos.take_profit}, trade {pos.trade_id}")
        record(WARN, "existujici pozice",
               "Bot ji pri startu prevezme. Kdyz ji tam nechces, zavri ji rucne.")

    # -- 4. odeslani prikazu (volitelne) ---------------------------------

    if not args.with_order_test:
        record(SKIP, "odeslani prikazu",
               "preskoceno. Pust s --with-order-test, "
               "aby se overila i cesta zapisu.")
    elif pos is not None:
        record(SKIP, "odeslani prikazu",
               "preskoceno - na instrumentu uz je otevrena pozice")
    else:
        price = float(bars["close"].iloc[-1])
        digits = 3 if args.instrument.upper().endswith("JPY") else 5
        pip = 0.01 if args.instrument.upper().endswith("JPY") else 0.0001
        sl = round(price - 50 * pip, digits)
        tp = round(price + 50 * pip, digits)
        cid = f"preflight-{uuid.uuid4().hex[:16]}"

        print(f"\n  Otevirám 1 jednotku {args.instrument} @ ~{price:.5f} "
              f"(SL {sl}, TP {tp})...")

        try:
            res = broker.market_order(
                args.instrument, "long", 1, sl, tp, cid
            )
        except (BrokerError, TransientError) as e:
            record(FAIL, "odeslani prikazu", str(e)[:400])
            return 1

        if not res.accepted:
            record(FAIL, "odeslani prikazu", res.reason)
            return 1

        record(OK, "odeslani prikazu",
               f"vyplneno {res.units:.0f} @ {res.fill_price:.5f}, "
               f"trade {res.trade_id}")

        # Idempotence: stejny client_id nesmi otevrit druhou pozici.
        dup = broker.market_order(args.instrument, "long", 1, sl, tp, cid)
        if dup.accepted and not dup.duplicate:
            record(FAIL, "idempotence prikazu",
                   "stejny client_id otevrel DRUHOU pozici - "
                   "vypadek site by zdvojil expozici")
        else:
            record(OK, "idempotence prikazu",
                   f"opakovany client_id odmitnut ({dup.reason})")

        # Kontrola, ze se SL a TP opravdu prilepily.
        check = broker.position(args.instrument)
        if check is None:
            record(FAIL, "cteni zpet", "pozice po otevreni neni videt")
        else:
            if check.stop_loss is None:
                record(FAIL, "stop-loss u brokera",
                       "pozice nema stop-loss! Bot na nej spoleha.")
            else:
                record(OK, "stop-loss u brokera", f"{check.stop_loss}")
            if check.take_profit is None:
                record(WARN, "take-profit u brokera", "neni nastaven")
            else:
                record(OK, "take-profit u brokera", f"{check.take_profit}")

        print("  Zavírám...")
        try:
            closed = broker.close_position(args.instrument, f"{cid}-close")
        except (BrokerError, TransientError) as e:
            record(FAIL, "zavreni pozice",
                   f"{str(e)[:300]}\n         POZOR: zustala otevrena pozice, "
                   f"zavri ji rucne v platforme.")
            return 1

        if closed.accepted:
            record(OK, "zavreni pozice", f"zavreno @ {closed.fill_price:.5f}")
        else:
            record(FAIL, "zavreni pozice",
                   f"{closed.reason} - ZKONTROLUJ UCET RUCNE")
            return 1

        if broker.position(args.instrument) is not None:
            record(FAIL, "uklid", "pozice je po zavreni porad videt - zkontroluj ucet")
        else:
            record(OK, "uklid", "zadna pozice nezustala")

    # -- shrnuti ----------------------------------------------------------

    fails = [r for r in results if r[0] == FAIL]
    warns = [r for r in results if r[0] == WARN]

    print("\n" + "=" * 66)
    if fails:
        print(f"  {len(fails)} SELHANI - bota nespoustej.")
        for _, name, detail in fails:
            print(f"    - {name}: {detail[:120]}")
        print("\n  Posli tenhle vypis a opravim to.")
        print("=" * 66)
        return 1

    print(f"  Vsechno proslo{f', {len(warns)} varovani' if warns else ''}.")
    if warns:
        for _, name, detail in warns:
            print(f"    ! {name}: {detail[:120]}")
    if not args.with_order_test:
        print("\n  Cesta zapisu neni overena. Pust jeste:")
        print("    python3 scripts/check_oanda.py --with-order-test")
    else:
        print("\n  Dalsi krok - nech tyden bezet dry-run:")
        print("    python3 scripts/run_bot.py --strategy london --dry-run")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
