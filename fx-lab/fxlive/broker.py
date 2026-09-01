"""Rozhrani k brokerovi.

Tri implementace:
  - `Broker`      - protokol, ktery musi splnit kazdy broker
  - `PaperBroker` - simulace v pameti, na testy a na dry-run
  - `OandaBroker` - OANDA v20 REST

Vsechno ostatni v botovi pracuje jen s protokolem, takze prechod
demo -> ostry ucet je zmena jednoho radku v konfiguraci.

IDEMPOTENCE
-----------
Kazdy prikaz nese `client_id`. Kdyz spojeni spadne po odeslani, ale pred
prijetim odpovedi, opakovany pokus se stejnym `client_id` NEVYTVORI druhou
pozici - broker ho odmitne jako duplicitu. Bez tohohle by ti vypadek site
zdvojnasobil pozici.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Optional, Protocol

log = logging.getLogger(__name__)


class BrokerError(RuntimeError):
    """Broker odmitl operaci. Nezotavitelne bez zasahu."""


class TransientError(RuntimeError):
    """Docasny problem (sit, rate limit). Ma smysl zkusit znovu."""


@dataclass
class Account:
    balance: float
    equity: float
    currency: str
    margin_used: float = 0.0
    open_position_count: int = 0


@dataclass
class BrokerPosition:
    """Pozice tak, jak ji vidi BROKER - ne jak si ji pamatuje bot.

    Pri startu se bot vzdycky ridi timhle, nikdy svym ulozenym stavem.
    """

    instrument: str
    side: str          # "long" | "short"
    units: float       # vzdy kladne
    entry_price: float
    unrealised_pnl: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    trade_id: Optional[str] = None
    open_time: Optional[str] = None


@dataclass
class OrderResult:
    accepted: bool
    trade_id: Optional[str]
    fill_price: Optional[float]
    units: float
    reason: str = ""
    duplicate: bool = False
    """True = tenhle client_id uz byl jednou vyrizen, nic noveho nevzniklo."""


class Broker(Protocol):
    def account(self) -> Account: ...
    def position(self, instrument: str) -> Optional[BrokerPosition]: ...
    def candles(self, instrument: str, granularity: str, count: int): ...
    def market_order(
        self, instrument: str, side: str, units: float,
        stop_loss: float, take_profit: Optional[float], client_id: str,
    ) -> OrderResult: ...
    def close_position(self, instrument: str, client_id: str) -> OrderResult: ...


# --------------------------------------------------------------------------
# Paper broker
# --------------------------------------------------------------------------


class PaperBroker:
    """Broker v pameti. Zadne site, zadne penize.

    Pouziva se na dva ucely:
      1. `--dry-run` - bot bezi proti zivym cenam, ale prikazy nikam neposila
      2. testy - deterministicke chovani

    Plneni je zamerne optimisticke (za mid cenu + spread). Neni to nahrada
    za backtest, jen kontrola, ze smycka bota funguje.
    """

    def __init__(
        self,
        balance: float = 10_000.0,
        currency: str = "USD",
        spread_pips: float = 1.2,
        pip: float = 0.0001,
        price_source=None,
    ):
        self._balance = balance
        self._currency = currency
        self._spread = spread_pips * pip
        self._positions: dict[str, BrokerPosition] = {}
        self._seen: dict[str, OrderResult] = {}
        self._price_source = price_source
        self._last_price: dict[str, float] = {}
        self._seq = 0
        self.fills: list[dict] = []

    # -- ceny -------------------------------------------------------------

    def set_price(self, instrument: str, price: float) -> None:
        self._last_price[instrument] = price

    def _price(self, instrument: str) -> float:
        if self._price_source is not None:
            return float(self._price_source(instrument))
        if instrument not in self._last_price:
            raise BrokerError(f"PaperBroker nezna cenu {instrument}")
        return self._last_price[instrument]

    # -- rozhrani ---------------------------------------------------------

    def account(self) -> Account:
        unreal = sum(self._unrealised(p) for p in self._positions.values())
        return Account(
            balance=self._balance,
            equity=self._balance + unreal,
            currency=self._currency,
            open_position_count=len(self._positions),
        )

    def position(self, instrument: str) -> Optional[BrokerPosition]:
        p = self._positions.get(instrument)
        if p is None:
            return None
        p.unrealised_pnl = self._unrealised(p)
        return p

    def candles(self, instrument, granularity, count):
        raise BrokerError(
            "PaperBroker neposkytuje data. Predej bare z jineho zdroje."
        )

    def market_order(
        self, instrument, side, units, stop_loss, take_profit, client_id,
    ) -> OrderResult:
        if client_id in self._seen:
            prev = self._seen[client_id]
            return OrderResult(
                accepted=prev.accepted, trade_id=prev.trade_id,
                fill_price=prev.fill_price, units=prev.units,
                reason="duplicitni client_id", duplicate=True,
            )

        if instrument in self._positions:
            res = OrderResult(False, None, None, 0.0, "pozice uz je otevrena")
            self._seen[client_id] = res
            return res

        units = abs(float(units))
        if units < 1:
            res = OrderResult(False, None, None, 0.0, "velikost pod 1 jednotku")
            self._seen[client_id] = res
            return res

        mid = self._price(instrument)
        fill = mid + self._spread / 2 if side == "long" else mid - self._spread / 2

        self._seq += 1
        tid = f"paper-{self._seq}"
        self._positions[instrument] = BrokerPosition(
            instrument=instrument, side=side, units=units, entry_price=fill,
            unrealised_pnl=0.0, stop_loss=stop_loss, take_profit=take_profit,
            trade_id=tid,
        )
        res = OrderResult(True, tid, fill, units)
        self._seen[client_id] = res
        self.fills.append(
            {"action": "open", "instrument": instrument, "side": side,
             "units": units, "price": fill, "trade_id": tid}
        )
        return res

    def close_position(self, instrument, client_id) -> OrderResult:
        if client_id in self._seen:
            prev = self._seen[client_id]
            return OrderResult(prev.accepted, prev.trade_id, prev.fill_price,
                               prev.units, "duplicitni client_id", duplicate=True)

        p = self._positions.pop(instrument, None)
        if p is None:
            res = OrderResult(False, None, None, 0.0, "zadna otevrena pozice")
            self._seen[client_id] = res
            return res

        mid = self._price(instrument)
        fill = mid - self._spread / 2 if p.side == "long" else mid + self._spread / 2
        direction = 1.0 if p.side == "long" else -1.0
        self._balance += direction * (fill - p.entry_price) * p.units

        res = OrderResult(True, p.trade_id, fill, p.units)
        self._seen[client_id] = res
        self.fills.append(
            {"action": "close", "instrument": instrument, "side": p.side,
             "units": p.units, "price": fill, "trade_id": p.trade_id}
        )
        return res

    # -- vnitrni ----------------------------------------------------------

    def _unrealised(self, p: BrokerPosition) -> float:
        try:
            mid = self._price(p.instrument)
        except BrokerError:
            return 0.0
        direction = 1.0 if p.side == "long" else -1.0
        return direction * (mid - p.entry_price) * p.units

    def trigger_stops(self, instrument: str, high: float, low: float) -> Optional[str]:
        """Simuluje zasah SL/TP. Vola se jen v testech a v dry-runu.

        Konzervativne stejne jako backtest: kdyz rozsah obsahuje oboji,
        predpoklada se stop.
        """
        p = self._positions.get(instrument)
        if p is None:
            return None

        if p.side == "long":
            hit_sl = p.stop_loss is not None and low <= p.stop_loss
            hit_tp = p.take_profit is not None and high >= p.take_profit
        else:
            hit_sl = p.stop_loss is not None and high >= p.stop_loss
            hit_tp = p.take_profit is not None and low <= p.take_profit

        if not (hit_sl or hit_tp):
            return None

        level = p.stop_loss if hit_sl else p.take_profit
        self._positions.pop(instrument)
        direction = 1.0 if p.side == "long" else -1.0
        self._balance += direction * (level - p.entry_price) * p.units
        reason = "stop" if hit_sl else "target"
        self.fills.append(
            {"action": "close", "instrument": instrument, "side": p.side,
             "units": p.units, "price": level, "trade_id": p.trade_id,
             "reason": reason}
        )
        return reason


# --------------------------------------------------------------------------
# OANDA v20
# --------------------------------------------------------------------------


class OandaBroker:
    """OANDA v20 REST.

    Token NIKDY nedavej do kodu. Predej pres promennou prostredi:

        export OANDA_TOKEN="..."
        export OANDA_ACCOUNT="101-004-XXXXXXX-001"

    `practice=True` miri na demo (api-fxpractice). `practice=False` na ostry
    ucet se skutecnymi penezi.
    """

    RETRYABLE = {408, 429, 500, 502, 503, 504}

    def __init__(
        self,
        token: str,
        account_id: str,
        practice: bool = True,
        timeout: int = 20,
        max_retries: int = 4,
    ):
        if not token:
            raise BrokerError("Chybi OANDA token.")
        if not account_id:
            raise BrokerError("Chybi ID uctu.")
        self._token = token
        self._account_id = account_id
        self._host = (
            "api-fxpractice.oanda.com" if practice else "api-fxtrade.oanda.com"
        )
        self.practice = practice
        self._timeout = timeout
        self._max_retries = max_retries

    # -- HTTP -------------------------------------------------------------

    def _request(self, method: str, path: str, body: Optional[dict] = None) -> dict:
        url = f"https://{self._host}{path}"
        data = json.dumps(body).encode() if body is not None else None
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept-Datetime-Format": "RFC3339",
        }

        last: Exception | None = None
        for attempt in range(self._max_retries):
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    return json.loads(resp.read() or b"{}")
            except urllib.error.HTTPError as e:
                payload = e.read().decode(errors="replace")
                if e.code in self.RETRYABLE:
                    last = TransientError(f"HTTP {e.code}: {payload[:300]}")
                else:
                    # 4xx krome vyjimek vyse je chyba na nasi strane.
                    raise BrokerError(f"HTTP {e.code}: {payload[:500]}") from e
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last = TransientError(f"sit: {e}")

            if attempt < self._max_retries - 1:
                wait = 2 ** attempt
                log.warning("OANDA %s %s selhalo (%s), zkousim za %ss",
                            method, path, last, wait)
                time.sleep(wait)

        raise TransientError(f"OANDA nedostupna po {self._max_retries} pokusech: {last}")

    # -- rozhrani ---------------------------------------------------------

    def account(self) -> Account:
        d = self._request("GET", f"/v3/accounts/{self._account_id}/summary")["account"]
        return Account(
            balance=float(d["balance"]),
            equity=float(d["NAV"]),
            currency=d["currency"],
            margin_used=float(d.get("marginUsed", 0)),
            open_position_count=int(d.get("openPositionCount", 0)),
        )

    def position(self, instrument: str) -> Optional[BrokerPosition]:
        """Otevrena pozice podle BROKERA.

        OANDA vraci long a short vetev zvlast. Bot drzi jen jednu stranu,
        takze se bere ta nenulova.
        """
        try:
            d = self._request(
                "GET", f"/v3/accounts/{self._account_id}/positions/{instrument}"
            )["position"]
        except BrokerError as e:
            if "404" in str(e):
                return None
            raise

        for side, key in (("long", "long"), ("short", "short")):
            leg = d.get(key, {})
            units = float(leg.get("units", 0) or 0)
            if units == 0:
                continue
            trade_ids = leg.get("tradeIDs") or []
            sl = tp = None
            open_time = None
            if trade_ids:
                td = self._request(
                    "GET", f"/v3/accounts/{self._account_id}/trades/{trade_ids[0]}"
                ).get("trade", {})
                open_time = td.get("openTime")
                if td.get("stopLossOrder"):
                    sl = float(td["stopLossOrder"]["price"])
                if td.get("takeProfitOrder"):
                    tp = float(td["takeProfitOrder"]["price"])
            return BrokerPosition(
                instrument=instrument, side=side, units=abs(units),
                entry_price=float(leg.get("averagePrice", 0) or 0),
                unrealised_pnl=float(leg.get("unrealizedPL", 0) or 0),
                stop_loss=sl, take_profit=tp,
                trade_id=trade_ids[0] if trade_ids else None,
                open_time=open_time,
            )
        return None

    def candles(self, instrument: str, granularity: str = "H1", count: int = 200):
        """Dokoncene svicky. Nedokoncena se ZAHAZUJE.

        Obchodovat podle nedokoncene svicky je look-ahead v zive podobe -
        rozhodujes se podle ceny, ktera se jeste zmeni.
        """
        import pandas as pd

        d = self._request(
            "GET",
            f"/v3/instruments/{instrument}/candles"
            f"?granularity={granularity}&count={min(count, 5000)}&price=M",
        )
        rows = []
        for c in d.get("candles", []):
            if not c.get("complete"):
                continue
            m = c["mid"]
            rows.append({
                "time": pd.Timestamp(c["time"]),
                "open": float(m["o"]), "high": float(m["h"]),
                "low": float(m["l"]), "close": float(m["c"]),
                "volume": int(c.get("volume", 0)),
            })
        if not rows:
            raise TransientError("OANDA nevratila zadne dokoncene svicky.")
        return pd.DataFrame(rows).set_index("time").sort_index()

    def market_order(
        self, instrument, side, units, stop_loss, take_profit, client_id,
    ) -> OrderResult:
        signed = int(round(abs(units))) * (1 if side == "long" else -1)
        if signed == 0:
            return OrderResult(False, None, None, 0.0, "velikost zaokrouhlena na nulu")

        digits = 3 if instrument.upper().endswith("JPY") else 5
        order: dict = {
            "type": "MARKET",
            "instrument": instrument,
            "units": str(signed),
            "timeInForce": "FOK",
            "positionFill": "DEFAULT",
            "stopLossOnFill": {"price": f"{stop_loss:.{digits}f}", "timeInForce": "GTC"},
            "clientExtensions": {"id": client_id, "tag": "fxlive"},
        }
        if take_profit is not None:
            order["takeProfitOnFill"] = {
                "price": f"{take_profit:.{digits}f}", "timeInForce": "GTC"
            }

        try:
            d = self._request(
                "POST", f"/v3/accounts/{self._account_id}/orders", {"order": order}
            )
        except BrokerError as e:
            # OANDA odmita duplicitni clientExtensions.id - presne to chceme.
            if "CLIENT_ORDER_ID_ALREADY_EXISTS" in str(e):
                return OrderResult(
                    False, None, None, 0.0,
                    "client_id uz existuje - prikaz uz byl odeslan", duplicate=True,
                )
            raise

        fill = d.get("orderFillTransaction")
        if not fill:
            reject = d.get("orderCancelTransaction") or d.get("orderRejectTransaction")
            reason = (reject or {}).get("reason", "neznamy duvod")
            return OrderResult(False, None, None, 0.0, f"prikaz nevyplnen: {reason}")

        return OrderResult(
            accepted=True,
            trade_id=(fill.get("tradeOpened") or {}).get("tradeID"),
            fill_price=float(fill["price"]),
            units=abs(float(fill["units"])),
        )

    def close_position(self, instrument: str, client_id: str) -> OrderResult:
        pos = self.position(instrument)
        if pos is None:
            return OrderResult(False, None, None, 0.0, "zadna otevrena pozice")

        body = {"longUnits": "ALL"} if pos.side == "long" else {"shortUnits": "ALL"}
        d = self._request(
            "PUT", f"/v3/accounts/{self._account_id}/positions/{instrument}/close", body
        )
        fill = d.get("longOrderFillTransaction") or d.get("shortOrderFillTransaction")
        if not fill:
            return OrderResult(False, None, None, 0.0, "zavreni nevyplneno")
        return OrderResult(
            accepted=True, trade_id=pos.trade_id,
            fill_price=float(fill["price"]), units=abs(float(fill["units"])),
        )
