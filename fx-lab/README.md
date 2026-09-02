# fx-lab

Backtest framework pro intradenní FX. Postavený tak, aby ti nelhal.

Většina amatérských backtestů ukáže zisk, který na živém účtu neexistuje. Není to náhoda. Jsou to tři konkrétní chyby, které se dělají pořád dokola. Tenhle framework je má ošetřené strukturálně — ne dobrou vůlí programátora.

---

## Co je ošetřené

**1. Look-ahead bias.** Strategie vidí data jen do `close[i]`. Její příkaz se vyplní na `open[i+1]`. Vynucuje to smyčka enginu. Nejde to obejít ani omylem.

**2. Náklady.** Spread, slippage, komise i swapy se účtují zvlášť. V reportu je řádek „náklady / hrubý zisk". U intradenního FX je to obvykle to nejdůležitější číslo na stránce.

**3. Přeoptimalizování.** Walk-forward ladí parametry na jednom okně a testuje na dalším, které model nikdy neviděl. Rozhoduje jen výsledek mimo vzorek.

Navíc konzervativní předpoklady: když bar obsahuje stop i target, počítá se stop. Když trh otevře za stopem, plní se na otevření, ne na stopu.

---

## Instalace

```bash
pip install pandas numpy pytest
```

Nic víc není potřeba. Žádné těžké závislosti.

---

## Rychlý start

```bash
# 1. Ověř, že engine počítá správně
python3 scripts/sanity_check.py

# 2. Pusť testy
python3 -m pytest tests/ -v

# 3. Backtest na reálných datech
python3 scripts/run_backtest.py --strategy london --data dukascopy \
    --symbol EURUSD --start 2022-01-01 --end 2026-01-01

# 4. Walk-forward
python3 scripts/run_backtest.py --strategy london --data dukascopy \
    --start 2020-01-01 --end 2026-01-01 --walkforward
```

---

## Data

**Dukascopy** je hlavní zdroj. Tick data zdarma, bez API klíče, roky zpětně, a hlavně **obsahují historický spread**. Bez skutečného spreadu je intradenní backtest k ničemu.

```bash
python3 scripts/run_backtest.py --data dukascopy --symbol EURUSD \
    --start 2022-01-01 --end 2026-01-01
```

První běh trvá 10–20 minut na rok dat. Stahuje se jeden soubor na hodinu. Pak už to jede z cache v `data/dukascopy_cache/`.

**OANDA** je druhá možnost. Výhoda: backtest i ostrý provoz jedou nad stejným zdrojem.

```bash
export OANDA_TOKEN="tvuj-token"
python3 scripts/run_backtest.py --data oanda --symbol EURUSD
```

Token vygeneruješ v účtu: *Manage API Access → Generate*. Nikdy ho nedávej do kódu ani do gitu.

---

## Strategie

Tři referenční implementace. Nejsou to doporučení — jsou to výchozí body a měřítko.

| Klíč | Co dělá |
|---|---|
| `london` | Proražení asijského rozsahu na otevření Londýna |
| `asia` | Mean reversion v klidných hodinách |
| `donchian` | Proražení N-barového maxima, trend-following |

`donchian` slouží hlavně jako laťka. Každá složitější strategie by měla být lepší než tahle triviální. Když není, ta složitost k ničemu není.

### Vlastní strategie

```python
from fxlab.engine import Order, Close
from fxlab.strategies.base import Strategy, atr

class MojeStrategie(Strategy):
    warmup = 50   # kolik barů potřebuješ, než začneš

    def on_bar(self, ctx):
        # ctx.bars = historie VČETNĚ aktuálního baru
        # ctx.position = otevřená pozice nebo None
        # ctx.equity = aktuální equity

        if ctx.position is not None:
            return None            # nebo Close("důvod")

        a = atr(ctx.bars, 14)
        close = float(ctx.last["close"])

        if tvoje_podminka:
            return Order(
                side="long",
                stop_loss=close - 2 * a,     # povinné
                take_profit=close + 3 * a,
                max_bars=48,
            )
        return None
```

Stop-loss je povinný. Příkaz bez něj engine odmítne. Velikost pozice se dopočítá ze vzdálenosti stopu tak, aby zásah stopu stál přesně `risk_per_trade` z equity.

---

## Jak číst report

Pořadí důležitosti, ne pořadí v reportu:

**1. Počet obchodů.** Pod 100 je výsledek statisticky bezcenný, ať vypadá jakkoli. Pod 30 se na něj ani nedívej.

**2. Náklady / hrubý zisk.** Nad 100 % znamená, že náklady převýšily hranu. Strategie je ztrátová jen kvůli poplatkům. U intradenního FX se to stává pořád.

**3. Expectancy v R.** Kolik vyděláš na jeden obchod v násobcích riskované částky. Pod nulou je konec debaty.

**4. Max drawdown a jeho délka.** Ne jak hluboko, ale jak dlouho. 18 měsíců pod vodou neustojí skoro nikdo, i když to nakonec vyjde.

**5. Max ztrát za sebou.** Kolik proher v řadě tě čeká. Když tam vidíš 11 a víš, že po páté vypneš bota, tahle strategie pro tebe není.

Úspěšnost a celkový výnos jsou dvě nejméně užitečná čísla. Úspěšnost 80 % s profit factorem 1.05 není hrana, jen přeházené rozložení.

---

## Postup, který dává smysl

1. `sanity_check.py` — ověř, že měřák měří
2. Stáhni reálná data, aspoň 4 roky
3. Pusť jednoduchý backtest, podívej se na cost drag
4. Když je expectancy záporná, **skonči**. Neexistuje kombinace parametrů, která to spraví — jen taková, která přeoptimalizuje.
5. Když je kladná, pusť walk-forward
6. Rozhoduje jen souhrn mimo vzorek
7. Když projde, paper trading na měsíce, ne na týdny
8. Teprve pak malý živý kapitál

Krok 4 přeskočí skoro každý. Proto skoro každý prodělá.

---

## Živý bot

Backtest je měřák. `fxlive/` je ta druhá půlka — bot, který se připojí k brokerovi a obchoduje.

**Používá přesně ty samé objekty strategií jako backtest.** Není tu druhá implementace logiky, kterou by šlo rozladit. Co jsi otestoval, to běží.

### Tři režimy, od nejbezpečnějšího

```bash
export OANDA_TOKEN="..."
export OANDA_ACCOUNT="101-004-1234567-001"

# 1. Živá data, žádné příkazy. Tady začni a nech to běžet týden.
python3 scripts/run_bot.py --strategy london --dry-run

# 2. Simulovaný broker na živých cenách. Ověří celou smyčku.
python3 scripts/run_bot.py --strategy london --paper

# 3. Skutečné příkazy na demo účtu.
python3 scripts/run_bot.py --strategy london --live

# 4. Ostrý účet. Vyžaduje napsat "ROZUMIM RIZIKU".
python3 scripts/run_bot.py --strategy london --live --real-money
```

### Co bot hlídá sám

**Riziková vrstva má právo veta** nad strategií. Oddělení je záměrné: strategii budeš měnit často, limity ne.

| Limit | Výchozí | Co dělá |
|---|---|---|
| `--risk` | 0,5 % | Kolik equity riskuješ na obchod |
| `--max-daily-loss` | 2 % | Denní ztráta, po které se vypne |
| `--max-drawdown` | 15 % | Propad od vrcholu, po kterém se vypne natrvalo |
| `--max-trades-per-day` | 10 | Pojistka proti smyčce chrlící příkazy |

Navíc odmítne stop pod 3 pipy nebo nad 200, pozici nad páku 30, obchod při zavřeném trhu a příkaz se stopem na špatné straně vstupu.

Denní halt se ruší novým dnem. **Drawdown halt ne** — ten musíš odblokovat ručně přes `--resume`, až zjistíš, co se stalo.

### Co bot dělá při startu

Ptá se **brokera**, ne svého uloženého stavu. Když najde pozici, o které nevěděl, převezme ji. Když čekal pozici, která tam není, zapomene ji.

Bez tohohle se po restartu snadno dostaneš do stavu, kdy bot otevře druhou pozici k té, o které neví.

Každý příkaz nese `client_id`. Když spadne spojení po odeslání, ale před odpovědí, opakovaný pokus se stejným ID nevytvoří druhou pozici.

### Ověření shody s backtestem

```bash
python3 scripts/replay_live.py --strategy london
```

Prožene ta samá data oběma cestami a porovná počet a směr obchodů. Musí sedět přesně. Rozdíl v equity je z jiného modelu plnění, ne z jiné logiky.

Tenhle nástroj už jednu skutečnou chybu našel: strategie s `max_bars` živě nezavíraly na čas, protože to vynucoval jen engine backtestu.

### Než pustíš bota poprvé

```bash
python3 scripts/check_oanda.py                    # čtecí cesty
python3 scripts/check_oanda.py --with-order-test  # i zápis, jen demo
```

Preflight projde všechny cesty, které bot používá, a u každé řekne, jestli sedí. Napojení na OANDA vznikalo bez přístupu k brokerským hostům, takže tohle je první místo, kde se potká se skutečným API. Když něco selže, vypíše i klíče, které reálně přišly.

### Co bot dělal

```bash
python3 scripts/bot_status.py            # souhrn za posledních 7 dní
python3 scripts/bot_status.py --days 30
python3 scripts/bot_status.py --trades   # seznam obchodů
python3 scripts/bot_status.py --tail 30  # poslední události
```

Čte žurnál, nesahá na účet. Ukáže, kdy bot naposledy žil, kolik signálů přišlo, **proč se nevstoupilo** (rozpad podle důvodů), a jestli někdy spadl do haltu.

Po týdnu dry-runu je tohle první věc, kterou spustíš.

### Kde bot běží

Na tvém stroji nebo VPS, ne v téhle relaci. Potřebuje běžet nepřetržitě.

V `deploy/` je hotová systemd unit:

```bash
sudo install -m 600 -o root -g root deploy/fxlive.env.example /etc/fxlive.env
sudo nano /etc/fxlive.env              # vyplň token a ID účtu

sudo cp deploy/fxlive.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now fxlive

journalctl -u fxlive -f
```

Restartuje se po pádu, ale **maximálně třikrát za deset minut**. Když padá častěji, je to skutečný problém a služba zůstane dole — lepší než bot, který se v smyčce restartuje a při každém startu něco pošle.

Na `SIGTERM` dokončí rozdělaný cyklus, takže `systemctl stop` nikdy nepřetne odesílání příkazu v půlce.

Stav i žurnál jsou v `data/live/`, takže restart stroje nevadí — po startu se bot sladí s brokerem.

---

## Co tenhle framework NEDĚLÁ

- **Nemodeluje partial fills ani rejekce.** Na retail objemech to nevadí.
- **Počítá jen s páry kótovanými v USD** (EURUSD, GBPUSD, AUDUSD). U JPY párů a crossů by přepočet P&L potřeboval kurz kvótované měny.
- **Nezná zprávy.** Spread se kolem NFP a zasedání centrálních bank rozšíří několikanásobně. Dukascopy data to částečně zachytí, konstantní spread ne.
- **Nevytvoří ti hranu.** Jen ti poctivě řekne, jestli nějakou máš.

---

## Struktura

```
fx-lab/
├── fxlab/                   MĚŘÁK
│   ├── engine.py            backtest smyčka, bez look-ahead
│   ├── costs.py             spread, slippage, komise, swapy
│   ├── metrics.py           vyhodnocení + verdikt
│   ├── walkforward.py       test na přeoptimalizování
│   ├── data.py              Dukascopy, OANDA, CSV, syntetika
│   └── strategies/          tři referenční strategie
├── fxlive/                  BOT
│   ├── broker.py            OANDA v20 + papírový broker
│   ├── risk.py              limity a sizing, má právo veta
│   ├── state.py             stav přežívající restart + žurnál
│   └── runner.py            hlavní smyčka
├── scripts/
│   ├── run_backtest.py      backtest a walk-forward
│   ├── sanity_check.py      ověření enginu na náhodných datech
│   ├── replay_live.py       shoda živé cesty s backtestem
│   ├── run_bot.py           spuštění bota
│   └── export_viz_data.py   data pro vizuální report
└── tests/
    ├── test_engine.py       16 testů proti chybám v backtestu
    └── test_live.py         29 testů proti chybám v živém provozu
```

---

## Varování

Intradenní obchodování je pro retail převážně ztrátová činnost. Data regulátorů i povinná zveřejnění brokerů dlouhodobě ukazují, že **70–90 % retailových účtů s CFD končí ve ztrátě**. Nedělají to hloupí lidé — dělá to spread, slippage a konkurence algoritmů.

Tenhle nástroj ti nepomůže vydělat. Pomůže ti zjistit dřív a levněji, že tvůj nápad nefunguje. To je jeho skutečná hodnota.

Není to investiční doporučení.
