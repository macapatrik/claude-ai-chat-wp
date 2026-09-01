"""Nacitani a priprava dat.

Podporovane zdroje:
  - Dukascopy: tick data zdarma, bez API klice, roky zpetne. Nejlepsi
    volny zdroj pro FX. Stahovani je pomale (jeden soubor na hodinu),
    proto se cachuje na disk.
  - OANDA v20: hotove svicky primo od brokera, u ktereho budes obchodovat.
    Vyhoda: backtest i ostry provoz jedou nad stejnym zdrojem.
  - CSV: cokoli vlastniho.

POZOR NA VIKENDY: FX trh je zavreny od patku 21:00 do nedele 21:00 UTC.
Resample vyrobi prazdne bary, ktere je nutne vyhodit - jinak ti indikatory
pocitaji z nul a backtest lze.
"""

from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import lzma
import os
import struct
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd

DUKASCOPY_URL = "https://datafeed.dukascopy.com/datafeed/{sym}/{y}/{m:02d}/{d:02d}/{h:02d}h_ticks.bi5"

# Delitel ceny podle instrumentu. JPY pary maji 3 desetinna mista.
POINT_DIVISOR = {"JPY": 1e3}
DEFAULT_DIVISOR = 1e5


def _divisor(symbol: str) -> float:
    for suffix, div in POINT_DIVISOR.items():
        if symbol.upper().endswith(suffix):
            return div
    return DEFAULT_DIVISOR


def pip_size_for(symbol: str) -> float:
    return 0.01 if symbol.upper().endswith("JPY") else 0.0001


# --------------------------------------------------------------------------
# Dukascopy
# --------------------------------------------------------------------------


def _decode_bi5(payload: bytes, hour_start: dt.datetime, divisor: float) -> pd.DataFrame:
    """Rozbali jeden .bi5 soubor na ticky.

    Format: LZMA-komprimovane zaznamy po 20 bajtech, big-endian:
      uint32 ms od zacatku hodiny, uint32 ask, uint32 bid, float32 ask vol,
      float32 bid vol.
    """
    if not payload:
        return pd.DataFrame(columns=["ask", "bid"])
    try:
        raw = lzma.LZMADecompressor().decompress(payload)
    except lzma.LZMAError:
        return pd.DataFrame(columns=["ask", "bid"])

    count = len(raw) // 20
    if count == 0:
        return pd.DataFrame(columns=["ask", "bid"])

    rows = struct.unpack(">" + "IIIff" * count, raw[: count * 20])
    arr = np.array(rows, dtype=np.float64).reshape(count, 5)

    ts = pd.to_datetime(hour_start, utc=True) + pd.to_timedelta(arr[:, 0], unit="ms")
    return pd.DataFrame(
        {"ask": arr[:, 1] / divisor, "bid": arr[:, 2] / divisor}, index=ts
    )


def _fetch_hour(symbol: str, when: dt.datetime, cache_dir: Path, timeout: int = 30):
    """Stahne jednu hodinu ticku. Vysledek cachuje na disk."""
    cache = cache_dir / symbol / f"{when:%Y-%m-%d-%H}.bi5"
    if cache.exists():
        return _decode_bi5(cache.read_bytes(), when, _divisor(symbol))

    url = DUKASCOPY_URL.format(
        sym=symbol.upper(), y=when.year, m=when.month - 1, d=when.day, h=when.hour
    )
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            payload = resp.read()
    except urllib.error.HTTPError as e:
        # 404 = trh zavreny (vikend, svatek). Normalni stav.
        if e.code == 404:
            payload = b""
        else:
            raise
    except urllib.error.URLError:
        return None  # sit selhala, zkusi se znovu

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(payload)
    return _decode_bi5(payload, when, _divisor(symbol))


def fetch_dukascopy(
    symbol: str,
    start: str | dt.date,
    end: str | dt.date,
    timeframe: str = "1h",
    cache_dir: str | Path = "data/dukascopy_cache",
    workers: int = 8,
    verbose: bool = True,
) -> pd.DataFrame:
    """Stahne tick data z Dukascopy a agreguje na svicky.

    Vraci DataFrame s open/high/low/close (mid) a `spread` v pipech.
    Skutecny historicky spread je pri backtestu intradenniho FX zasadni -
    a Dukascopy je jeden z mala volnych zdroju, ktery ho ma.

    Rok EURUSD hodinovych dat = ~6000 souboru, pocitej s 10-20 minutami
    pri prvnim behu. Pak uz to jede z cache.
    """
    cache_dir = Path(cache_dir)
    start = pd.Timestamp(start).to_pydatetime().replace(tzinfo=None)
    end = pd.Timestamp(end).to_pydatetime().replace(tzinfo=None)

    hours = []
    cur = start.replace(minute=0, second=0, microsecond=0)
    while cur < end:
        # Vikend preskocime rovnou, usetri to tisice HTTP requestu.
        if not (cur.weekday() == 5 or (cur.weekday() == 6 and cur.hour < 21)
                or (cur.weekday() == 4 and cur.hour >= 21)):
            hours.append(cur)
        cur += dt.timedelta(hours=1)

    if verbose:
        print(f"Dukascopy {symbol}: {len(hours)} hodin ke stazeni/nacteni...")

    frames = []
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch_hour, symbol, h, cache_dir): h for h in hours}
        done = 0
        for fut in cf.as_completed(futures):
            df = fut.result()
            if df is not None and len(df):
                frames.append(df)
            done += 1
            if verbose and done % 500 == 0:
                print(f"  {done}/{len(hours)}")

    if not frames:
        raise RuntimeError(
            "Dukascopy nevratil zadna data. Zkontroluj symbol a pripojeni."
        )

    ticks = pd.concat(frames).sort_index()
    return ticks_to_bars(ticks, timeframe)


def ticks_to_bars(ticks: pd.DataFrame, timeframe: str = "1h") -> pd.DataFrame:
    """Agreguje ticky (sloupce ask/bid) na OHLC svicky z mid ceny."""
    mid = (ticks["ask"] + ticks["bid"]) / 2.0
    spread = (ticks["ask"] - ticks["bid"])

    bars = mid.resample(timeframe).ohlc()
    bars["ticks"] = mid.resample(timeframe).count()
    bars["spread"] = spread.resample(timeframe).mean()

    bars = bars[bars["ticks"] > 0].copy()
    # Spread prevedeme na pipy az v engine podle pip_size instrumentu.
    return bars


# --------------------------------------------------------------------------
# OANDA v20
# --------------------------------------------------------------------------


def fetch_oanda(
    instrument: str = "EUR_USD",
    granularity: str = "H1",
    count: int = 5000,
    start: Optional[str] = None,
    end: Optional[str] = None,
    token: Optional[str] = None,
    practice: bool = True,
) -> pd.DataFrame:
    """Stahne svicky z OANDA v20 API.

    Token si vygenerujes v uctu: Manage API Access -> Generate.
    Nikdy ho nedavej do kodu - predej pres promennou prostredi:

        export OANDA_TOKEN="..."

    OANDA vraci max 5000 svicek na request. Pro delsi historii volej
    opakovane s posouvanim `start`.
    """
    import json

    token = token or os.environ.get("OANDA_TOKEN")
    if not token:
        raise RuntimeError(
            "Chybi OANDA token. Nastav promennou prostredi OANDA_TOKEN."
        )

    host = "api-fxpractice.oanda.com" if practice else "api-fxtrade.oanda.com"
    params = [f"granularity={granularity}", "price=M"]
    if start:
        params.append(f"from={pd.Timestamp(start).isoformat()}Z")
        if end:
            params.append(f"to={pd.Timestamp(end).isoformat()}Z")
    else:
        params.append(f"count={count}")

    url = f"https://{host}/v3/instruments/{instrument}/candles?" + "&".join(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        payload = json.loads(resp.read())

    rows = []
    for c in payload.get("candles", []):
        if not c.get("complete"):
            continue  # nedokoncena svicka = look-ahead, zahodit
        m = c["mid"]
        rows.append(
            {
                "time": pd.Timestamp(c["time"]),
                "open": float(m["o"]), "high": float(m["h"]),
                "low": float(m["l"]), "close": float(m["c"]),
                "volume": int(c.get("volume", 0)),
            }
        )

    if not rows:
        raise RuntimeError("OANDA nevratila zadne dokoncene svicky.")
    return pd.DataFrame(rows).set_index("time").sort_index()


# --------------------------------------------------------------------------
# CSV a uklid
# --------------------------------------------------------------------------


def load_csv(path: str | Path, time_col: str = "time", tz: str = "UTC") -> pd.DataFrame:
    df = pd.read_csv(path)
    df[time_col] = pd.to_datetime(df[time_col], utc=(tz == "UTC"))
    df = df.set_index(time_col).sort_index()
    df.columns = [c.lower() for c in df.columns]
    return df


def clean(bars: pd.DataFrame, max_gap_bars: int = 5) -> pd.DataFrame:
    """Vyhodi prazdne bary, duplikaty a zjevne chybna data.

    Vraci ocisteny DataFrame. Vypise, co vyhodil - vzdycky se na to podivej,
    velky pocet vyhozenych baru znamena problem se zdrojem dat.
    """
    before = len(bars)
    bars = bars[~bars.index.duplicated(keep="first")].sort_index()

    for col in ("open", "high", "low", "close"):
        if col not in bars.columns:
            raise ValueError(f"Chybi sloupec {col}")

    bars = bars.dropna(subset=["open", "high", "low", "close"])
    bars = bars[(bars[["open", "high", "low", "close"]] > 0).all(axis=1)]

    # OHLC konzistence
    ok = (
        (bars.high >= bars.low)
        & (bars.high >= bars.open) & (bars.high >= bars.close)
        & (bars.low <= bars.open) & (bars.low <= bars.close)
    )
    bars = bars[ok]

    # Nesmyslne skoky - vic nez 5 % na jednom baru je u majoru chyba dat.
    ret = bars.close.pct_change().abs()
    bars = bars[(ret < 0.05) | ret.isna()]

    removed = before - len(bars)
    if removed:
        print(f"clean(): vyhozeno {removed} baru z {before} ({removed/before:.1%})")
    return bars


def add_session_flags(bars: pd.DataFrame) -> pd.DataFrame:
    """Prida sloupce pro obchodni session (casy v UTC).

    Tokio 00-08, Londyn 07-16, New York 12-21.
    Prekryv Londyn/NY (12-16) je nejlikvidnejsi cast dne.
    """
    out = bars.copy()
    h = out.index.hour
    out["asia"] = (h >= 0) & (h < 8)
    out["london"] = (h >= 7) & (h < 16)
    out["newyork"] = (h >= 12) & (h < 21)
    out["overlap"] = (h >= 12) & (h < 16)
    return out


# --------------------------------------------------------------------------
# Syntetika - JEN na testovani mechaniky, nikdy na hodnoceni strategie
# --------------------------------------------------------------------------


def synthetic_fx(
    start: str = "2021-01-01",
    end: str = "2026-01-01",
    timeframe: str = "1h",
    start_price: float = 1.1000,
    annual_vol: float = 0.075,
    seed: int = 42,
) -> pd.DataFrame:
    """Vygeneruje umely FX rad s realistickou strukturou.

    VAROVANI
    --------
    Tohle NENI nahrada za realna data. Slouzi vyhradne k overeni, ze engine
    pocita spravne. Vysledek jakekoli strategie na techto datech ti o jeji
    ziskovosti nerekne vubec nic - proces je z definice bez hrany.

    Kdyz na tomhle nejaka strategie "vydelava", je to dukaz chyby v kodu
    nebo nahoda, ne objev.
    """
    rng = np.random.default_rng(seed)

    idx = pd.date_range(start, end, freq=timeframe, tz="UTC")
    # Vikendy ven - FX je zavrene pa 21:00 az ne 21:00 UTC.
    wd, hr = idx.weekday, idx.hour
    open_market = ~((wd == 5) | ((wd == 6) & (hr < 21)) | ((wd == 4) & (hr >= 21)))
    idx = idx[open_market]
    n = len(idx)

    # Intradenni sezonnost volatility: nejvic v prekryvu Londyn/NY.
    hour_vol = np.ones(n)
    h = idx.hour
    hour_vol[(h >= 0) & (h < 7)] = 0.6      # Asie
    hour_vol[(h >= 7) & (h < 12)] = 1.2     # Londyn
    hour_vol[(h >= 12) & (h < 16)] = 1.5    # prekryv
    hour_vol[(h >= 16) & (h < 21)] = 0.9    # NY odpoledne

    bars_per_year = 6260
    sigma = annual_vol / np.sqrt(bars_per_year)

    # GARCH-like shlukovani volatility
    vol = np.empty(n)
    vol[0] = sigma
    for i in range(1, n):
        vol[i] = np.sqrt(0.94 * vol[i - 1] ** 2 + 0.06 * sigma**2)
    vol *= hour_vol

    rets = rng.standard_normal(n) * vol
    close = start_price * np.exp(np.cumsum(rets))

    # Dopocitani OHLC tak, aby byly konzistentni.
    open_ = np.empty(n)
    open_[0] = start_price
    open_[1:] = close[:-1]
    wick = np.abs(rng.standard_normal(n)) * vol * close * 0.5
    high = np.maximum(open_, close) + wick
    low = np.minimum(open_, close) - wick

    spread_pips = 0.8 + 1.4 / hour_vol  # v klidu je spread sirsi

    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close,
         "spread": spread_pips * 0.0001},
        index=idx,
    )
