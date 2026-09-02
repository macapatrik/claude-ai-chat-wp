#!/usr/bin/env python3
"""Zkouska, jestli jde ovladat MetaTrader 5 z Pythonu.

PUSTIT PRED TIM, NEZ SE PISE ADAPTER
------------------------------------
Adapter pro MT5 je nekolik set radku kodu. Nema smysl ho psat, dokud
nevime, ze zaklad vubec funguje: ze se balicek nainstaluje, ze se pripoji
k terminalu, ze najde tvuj symbol a ze vrati svicky.

Tenhle skript overi presne tohle a nic vic. NEOBCHODUJE. Neposila zadny
prikaz. Jen cte.

CO POTREBUJES PREDEM
--------------------
1. Stazeny a spusteny MetaTrader 5 od TMS (ne jinou verzi - kazdy broker
   ma vlastni build, ktery mirí na jeho servery).
2. V MT5 prihlaseny demo ucet.
3. V MT5: Nastroje -> Moznosti -> Expert Advisors ->
   zaskrtnout "Povolit algoritmicke obchodovani".
4. pip install MetaTrader5

POZOR NA WINDOWS
----------------
Balicek `MetaTrader5` je jen pro Windows. Na Linuxu a macOS bezi jedine
pres Wine, a to s vlastnimi problemy. Kdyz jsi na Linuxu, rekni to -
budeme resit jinak.

Spusteni:
    python scripts/check_mt5.py
    python scripts/check_mt5.py --symbol EURUSD.pro
"""

from __future__ import annotations

import argparse
import sys

OK, FAIL, WARN = "  OK  ", " FAIL ", " WARN "
problems: list[str] = []


def say(status: str, name: str, detail: str = "") -> None:
    print(f"[{status}] {name}" + (f"\n         {detail}" if detail else ""))
    if status == FAIL:
        problems.append(f"{name}: {detail}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="EURUSD.pro",
                   help="Presne tak, jak je v Prehledu trhu (vcetne pripony)")
    p.add_argument("--bars", type=int, default=200)
    args = p.parse_args()

    print("=" * 66)
    print("  Zkouska MetaTrader 5")
    print("=" * 66)

    # -- 1. balicek -------------------------------------------------------

    try:
        import MetaTrader5 as mt5
    except ImportError:
        say(FAIL, "balicek MetaTrader5", "neni nainstalovan: pip install MetaTrader5")
        print("\n  Pokud jsi na Linuxu nebo macOS, balicek tam primo nefunguje.")
        return 2

    say(OK, "balicek MetaTrader5", f"verze {mt5.__version__}")

    # -- 2. pripojeni k terminalu -----------------------------------------

    if not mt5.initialize():
        code, msg = mt5.last_error()
        say(FAIL, "pripojeni k terminalu", f"chyba {code}: {msg}")
        print("\n  Nejcastejsi priciny:")
        print("    - MT5 nebezi (spust ho a nech otevreny)")
        print("    - neni prihlaseny ucet")
        print("    - neni povoleno algoritmicke obchodovani v Moznostech")
        return 1

    try:
        term = mt5.terminal_info()
        say(OK, "pripojeni k terminalu",
            f"{term.name} build {term.build}, {term.company}")

        if not term.trade_allowed:
            say(FAIL, "algoritmicke obchodovani",
                "je VYPNUTE. Nastroje -> Moznosti -> Expert Advisors -> "
                "Povolit algoritmicke obchodovani")
        else:
            say(OK, "algoritmicke obchodovani", "povoleno")

        # -- 3. ucet ------------------------------------------------------

        acct = mt5.account_info()
        if acct is None:
            say(FAIL, "ucet", "nelze precist - je prihlaseny?")
            return 1

        say(OK, "ucet",
            f"#{acct.login} u {acct.server}, "
            f"zustatek {acct.balance:,.2f} {acct.currency}, "
            f"paka 1:{acct.leverage}")

        demo = "demo" in str(acct.server).lower() or acct.trade_mode == 0
        if demo:
            say(OK, "typ uctu", "DEMO")
        else:
            say(WARN, "typ uctu",
                "vypada to na OSTRY ucet. Zacinej na demu.")

        if acct.currency != "USD":
            say(WARN, "mena uctu",
                f"ucet je v {acct.currency}. Vypocet velikosti pozice zatim "
                f"predpoklada USD - bude potreba prepocet kurzem.")

        # -- 4. symbol ----------------------------------------------------

        info = mt5.symbol_info(args.symbol)
        if info is None:
            say(FAIL, "symbol", f"{args.symbol} neexistuje")
            forex = [s.name for s in (mt5.symbols_get() or [])
                     if "EUR" in s.name and "USD" in s.name][:10]
            if forex:
                print(f"         Podobne dostupne: {', '.join(forex)}")
            return 1

        if not info.visible:
            mt5.symbol_select(args.symbol, True)
            info = mt5.symbol_info(args.symbol)

        say(OK, "symbol", f"{info.name}, {info.digits} desetinnych mist, "
                          f"bod {info.point}")
        say(OK, "obchodni parametry",
            f"min {info.volume_min} lotu, krok {info.volume_step}, "
            f"max {info.volume_max}, velikost kontraktu {info.trade_contract_size:,.0f}")

        tick = mt5.symbol_info_tick(args.symbol)
        if tick and tick.ask and tick.bid:
            spread_pts = (tick.ask - tick.bid) / info.point
            say(OK, "aktualni cena",
                f"bid {tick.bid}, ask {tick.ask}, spread {spread_pts:.1f} bodu")
        else:
            say(WARN, "aktualni cena", "zadny tick - je trh otevreny?")

        # -- 5. svicky ----------------------------------------------------

        rates = mt5.copy_rates_from_pos(args.symbol, mt5.TIMEFRAME_H1, 0, args.bars)
        if rates is None or len(rates) == 0:
            say(FAIL, "svicky", "zadna data")
            return 1

        import pandas as pd
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        say(OK, "svicky",
            f"{len(df)} hodinovych, {df['time'].iloc[0]} -> {df['time'].iloc[-1]}")
        say(OK, "sloupce", ", ".join(df.columns))

        # -- 6. otevrene pozice -------------------------------------------

        positions = mt5.positions_get(symbol=args.symbol)
        if positions:
            say(WARN, "otevrene pozice",
                f"{len(positions)} na {args.symbol} - bot by je prevzal")
        else:
            say(OK, "otevrene pozice", "zadne")

    finally:
        mt5.shutdown()

    # -- shrnuti ----------------------------------------------------------

    print("\n" + "=" * 66)
    if problems:
        print(f"  {len(problems)} problem(u) - adapter zatim nema smysl psat:")
        for pr in problems:
            print(f"    - {pr}")
    else:
        print("  Vsechno funguje. Posli mi tenhle vypis a napisu adapter.")
        print("  Dulezite jsou hlavne: mena uctu, presny nazev symbolu,")
        print("  velikost kontraktu a minimalni lot.")
    print("=" * 66)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
