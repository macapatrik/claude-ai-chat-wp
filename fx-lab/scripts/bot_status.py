#!/usr/bin/env python3
"""Ukaze, co bot delal. Cte zurnal, nesaha na ucet.

Po tydnu dry-runu tohle odpovi na otazky, ktere te budou zajimat:
kolik signalu prislo, kolik jich rizikova vrstva zamitla a proc, jestli
bot nekdy vypadl, a kdy naposledy zil.

    python3 scripts/bot_status.py
    python3 scripts/bot_status.py --days 7
    python3 scripts/bot_status.py --trades          # jen seznam obchodu
    python3 scripts/bot_status.py --tail 30         # posledni udalosti

Nic nemeni a nic nikam neposila.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

UTC = dt.timezone.utc

# Jak se jednotlive druhy udalosti ukazuji uzivateli.
LABELS = {
    "start": "start bota",
    "stop": "ukonceni",
    "bar": "zpracovana svicka",
    "open": "OTEVRENO",
    "close": "ZAVRENO",
    "closed_by_broker": "zavreno brokerem (stop/target)",
    "dry_open": "dry-run: otevrel by",
    "dry_close": "dry-run: zavrel by",
    "blocked": "vstup zablokovan",
    "rejected": "prikaz zamitnut",
    "order_failed": "prikaz neprijat brokerem",
    "close_failed": "zavreni neproslo",
    "halt": "HALT",
    "broker_error": "chyba brokera",
    "fatal": "FATALNI CHYBA",
    "reconcile_pending": "dohledani nevyrizeneho prikazu",
}

PROBLEMS = {"halt", "fatal", "broker_error", "order_failed", "close_failed"}

# Kratsi varianty do tabulky obchodu, aby se sloupce nerozjely.
SHORT = {
    "open": "otevreno",
    "close": "zavreno",
    "closed_by_broker": "zavreno stopem/targetem",
    "dry_open": "dry-run vstup",
    "dry_close": "dry-run vystup",
}


def find_journals(state_dir: Path) -> list[Path]:
    return sorted(state_dir.glob("*.journal.sqlite"))


def load(path: Path, since: dt.datetime | None) -> list[dict]:
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    q = "SELECT * FROM events"
    args: list = []
    if since:
        q += " WHERE ts >= ?"
        args.append(since.isoformat())
    q += " ORDER BY id ASC"
    rows = [dict(r) for r in db.execute(q, args)]
    db.close()
    return rows


def fmt_ts(ts: str) -> str:
    try:
        return dt.datetime.fromisoformat(ts).strftime("%d.%m. %H:%M")
    except (ValueError, TypeError):
        return (ts or "")[:16]


def detail_text(ev: dict) -> str:
    d = ev.get("detail")
    if not d:
        return ""
    try:
        parsed = json.loads(d)
    except (json.JSONDecodeError, TypeError):
        return str(d)
    if isinstance(parsed, dict):
        return ", ".join(f"{k}={v}" for k, v in parsed.items())
    return str(parsed)


def summarise(name: str, events: list[dict], days: int) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {name}")
    print(f"{'=' * 70}")

    if not events:
        print(f"  Za poslednich {days} dni zadna udalost.")
        print("  Bot nebezel, nebo bezi jinam nez do teto slozky.")
        return

    kinds = Counter(e["kind"] for e in events)

    # Cas se bere jako min/max, ne prvni/posledni radek: zaznamy o barech
    # nesou cas svicky, provozni udalosti cas systemu, a ty se nemusi
    # shodovat (napr. pri prehravani historie).
    stamps = sorted(e["ts"] for e in events if e.get("ts"))
    first_ts, last_ts = (stamps[0], stamps[-1]) if stamps else ("", "")

    # -- zivotni znamky ---------------------------------------------------

    print(f"\n  Obdobi     {fmt_ts(first_ts)}  ->  {fmt_ts(last_ts)}")
    print(f"  Udalosti   {len(events):,}")

    try:
        age = dt.datetime.now(UTC) - dt.datetime.fromisoformat(last_ts)
        mins = age.total_seconds() / 60
        if mins < 90:
            live = f"pred {mins:.0f} min"
        elif mins < 60 * 48:
            live = f"pred {mins / 60:.1f} h"
        else:
            live = f"pred {mins / 1440:.1f} dny"
        warn = "   <- bot nejspis nebezi" if mins > 180 else ""
        print(f"  Naposledy  {live}{warn}")
    except (ValueError, TypeError):
        pass

    starts = [e for e in events if e["kind"] == "start"]
    if starts:
        s = starts[-1]
        try:
            info = json.loads(s.get("detail") or "{}")
            mode = "dry-run" if info.get("dry_run") else "ostry"
            summary = f"{info.get('strategy', '?')}, {mode}"
            if info.get("halted"):
                summary += ", startoval v HALTU"
        except (json.JSONDecodeError, TypeError):
            summary = detail_text(s)[:60]
        print(f"  Posledni start  {fmt_ts(s['ts'])}  ({summary})")
    if len(starts) > 1:
        print(f"  Poctu startu    {len(starts)} - bot se restartoval")

    # -- problemy nejdriv -------------------------------------------------

    problems = [e for e in events if e["kind"] in PROBLEMS]
    if problems:
        print(f"\n  PROBLEMY ({len(problems)})")
        for e in problems[-8:]:
            print(f"    {fmt_ts(e['ts'])}  {LABELS.get(e['kind'], e['kind'])}: "
                  f"{detail_text(e)[:90]}")
    else:
        print("\n  Zadny halt ani chyba.")

    # -- co bot delal -----------------------------------------------------

    print("\n  UDALOSTI")
    for kind, count in kinds.most_common():
        label = LABELS.get(kind, kind)
        print(f"    {count:>6,}  {label}")

    # -- proc nevstoupil --------------------------------------------------

    blocked = [e for e in events if e["kind"] == "blocked"]
    rejected = [e for e in events if e["kind"] == "rejected"]

    if blocked or rejected:
        print("\n  PROC SE NEVSTOUPILO")
        reasons = Counter()
        for e in blocked + rejected:
            txt = detail_text(e)
            # Zkratit na duvod bez cisel, at se stejne pripady seskupi.
            key = txt.split("(")[0].strip()[:60]
            reasons[key] += 1
        for reason, count in reasons.most_common(8):
            print(f"    {count:>6,}  {reason}")

    # -- obchody ----------------------------------------------------------

    opens = [e for e in events if e["kind"] in ("open", "dry_open")]
    closes = [e for e in events if e["kind"] in ("close", "closed_by_broker")]

    if opens:
        dry = opens[0]["kind"] == "dry_open"
        print(f"\n  {'SIGNALY (dry-run, nic se neposlalo)' if dry else 'OBCHODY'}"
              f": {len(opens)}")
        sides = Counter(e["side"] for e in opens if e["side"])
        print(f"    long {sides.get('long', 0)}, short {sides.get('short', 0)}")

        if not dry and closes:
            print(f"    zavreno: {len(closes)}")

        eq = [e["equity"] for e in events if e.get("equity") is not None]
        if len(eq) >= 2:
            change = eq[-1] - eq[0]
            pct = change / eq[0] * 100 if eq[0] else 0
            sign = "+" if change >= 0 else "−"
            print(f"    equity {eq[0]:,.2f} -> {eq[-1]:,.2f} "
                  f"({sign}{abs(change):,.2f}, {sign}{abs(pct):.2f} %)")
    else:
        bars = kinds.get("bar", 0)
        if bars:
            print(f"\n  Zadny vstupni signal za {bars:,} svicek.")
            print("    Bud strategie ceka na podminky, nebo je prilis vyberova.")


def list_trades(events: list[dict]) -> None:
    rows = [e for e in events
            if e["kind"] in ("open", "close", "dry_open", "closed_by_broker")]
    if not rows:
        print("  Zadne obchody.")
        return

    print(f"\n  {'cas':<14}{'udalost':<26}{'strana':<8}{'jednotek':>10}"
          f"{'cena':>10}{'equity':>12}")
    print("  " + "-" * 80)
    for e in rows:
        units = f"{e['units']:,.0f}" if e["units"] else "-"
        price = f"{e['price']:.5f}" if e["price"] else "-"
        equity = f"{e['equity']:,.0f}" if e["equity"] else "-"
        label = SHORT.get(e["kind"], LABELS.get(e["kind"], e["kind"]))
        print(f"  {fmt_ts(e['ts']):<14}{label:<26}"
              f"{(e['side'] or '-'):<8}"
              f"{units:>10}{price:>10}{equity:>12}")


def tail(events: list[dict], n: int) -> None:
    print(f"\n  Poslednich {n} udalosti:\n")
    for e in events[-n:]:
        d = detail_text(e)
        print(f"  {fmt_ts(e['ts']):<14}{LABELS.get(e['kind'], e['kind']):<24}"
              f"{d[:60]}")


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--state-dir", default="data/live")
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--trades", action="store_true", help="Vypsat obchody")
    p.add_argument("--tail", type=int, metavar="N", help="Poslednich N udalosti")
    args = p.parse_args()

    state_dir = Path(args.state_dir)
    if not state_dir.exists():
        print(f"Slozka {state_dir} neexistuje. Bot jeste nebezel?")
        return 1

    journals = find_journals(state_dir)
    if not journals:
        print(f"V {state_dir} nejsou zadne zurnaly (*.journal.sqlite).")
        return 1

    since = dt.datetime.now(UTC) - dt.timedelta(days=args.days)

    for path in journals:
        name = path.name.replace(".journal.sqlite", "")
        try:
            events = load(path, since)
        except sqlite3.Error as e:
            print(f"\n  {name}: zurnal se nepodarilo precist ({e})")
            continue

        if args.trades:
            print(f"\n{'=' * 70}\n  {name}\n{'=' * 70}")
            list_trades(events)
        elif args.tail:
            print(f"\n{'=' * 70}\n  {name}\n{'=' * 70}")
            tail(events, args.tail)
        else:
            summarise(name, events, args.days)

        # Aktualni stav vedle zurnalu
        state_path = state_dir / f"{name}.state.json"
        if state_path.exists() and not (args.trades or args.tail):
            try:
                st = json.loads(state_path.read_text())
                risk = st.get("risk", {})
                print("\n  ULOZENY STAV")
                print(f"    posledni svicka   {st.get('last_bar_time', '-')[:16]}")
                print(f"    otevreny obchod   {st.get('open_trade_id') or 'zadny'}")
                print(f"    obchodu dnes      {risk.get('trades_today', 0)}")
                print(f"    vrchol equity     {risk.get('peak_equity', 0):,.2f}")
                if risk.get("halted"):
                    print(f"    HALT              {risk.get('halt_reason', '')}")
                    print("    -> pust s --resume, az zjistis proc")
            except (json.JSONDecodeError, OSError):
                pass

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
