"""Stav bota, ktery musi prezit restart, a zaznam vseho, co se stalo.

DVE ODDELENE VECI
-----------------
`BotState` je male, prepisuje se, drzi jen "kde jsem". Uklada se atomicky -
zapis do docasneho souboru a prejmenovani. Kdyby proces spadl uprostred
zapisu, zustane predchozi platny stav misto pulky noveho.

`Journal` je append-only SQLite. Nikdy se nemaze. Kdyz se neco pokazi,
tohle je jediny zdroj pravdy o tom, co bot delal a proc.

DULEZITE: ulozeny stav NENI zdroj pravdy o pozicich. Ten je vzdycky broker.
Pri startu se pozice ctou z brokera - viz `Runner.reconcile`.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .risk import RiskState

log = logging.getLogger(__name__)


@dataclass
class BotState:
    last_bar_time: str = ""
    """Cas posledni zpracovane svicky. Brani dvojimu zpracovani po restartu."""

    risk: RiskState = field(default_factory=RiskState)

    pending_client_id: str = ""
    """client_id prikazu, u ktereho nevime, jestli prosel.

    Kdyz tady po startu neco najdes, znamena to, ze bot spadl mezi odeslanim
    prikazu a potvrzenim. Reconcile to vyresi dotazem na brokera.
    """

    open_trade_id: str = ""
    strategy_name: str = ""

    open_bars_held: int = 0
    """Kolik baru uz drzime otevrenou pozici. Musi prezit restart."""

    open_max_bars: int = 0
    """Vynucene zavreni po N barech, prevzate z prikazu. 0 = neomezeno.

    Bez tohohle by strategie pouzivajici `max_bars` (napr. DonchianBreakout)
    zive nikdy nezavrela na cas a chovala se jinak nez v backtestu.
    """

    def to_dict(self) -> dict:
        return {
            "last_bar_time": self.last_bar_time,
            "risk": self.risk.to_dict(),
            "pending_client_id": self.pending_client_id,
            "open_trade_id": self.open_trade_id,
            "strategy_name": self.strategy_name,
            "open_bars_held": self.open_bars_held,
            "open_max_bars": self.open_max_bars,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BotState":
        return cls(
            last_bar_time=d.get("last_bar_time", ""),
            risk=RiskState.from_dict(d.get("risk", {})),
            pending_client_id=d.get("pending_client_id", ""),
            open_trade_id=d.get("open_trade_id", ""),
            strategy_name=d.get("strategy_name", ""),
            open_bars_held=int(d.get("open_bars_held", 0)),
            open_max_bars=int(d.get("open_max_bars", 0)),
        )


class StateStore:
    """Atomicky ulozeny JSON stav."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> BotState:
        if not self.path.exists():
            return BotState()
        try:
            return BotState.from_dict(json.loads(self.path.read_text()))
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            # Poskozeny stav radeji zahodit nez z nej cist nesmysly.
            log.error("Stav %s je poskozeny (%s), zacinam s prazdnym.", self.path, e)
            backup = self.path.with_suffix(".corrupt")
            self.path.replace(backup)
            log.error("Puvodni soubor odlozen do %s", backup)
            return BotState()

    def save(self, state: BotState) -> None:
        payload = json.dumps(state.to_dict(), indent=1)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  ts           TEXT NOT NULL,
  kind         TEXT NOT NULL,
  instrument   TEXT,
  side         TEXT,
  units        REAL,
  price        REAL,
  stop_loss    REAL,
  take_profit  REAL,
  trade_id     TEXT,
  client_id    TEXT,
  equity       REAL,
  detail       TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind);
"""


class Journal:
    """Append-only zaznam. Kazde rozhodnuti a kazdy prikaz.

    Kdyz se bota zeptas "proc jsi to udelal", odpoved je tady.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path), isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)

    def write(self, kind: str, ts: str, **fields: Any) -> None:
        detail = fields.pop("detail", None)
        if isinstance(detail, (dict, list)):
            detail = json.dumps(detail, ensure_ascii=False)
        cols = ["ts", "kind", "detail"] + list(fields)
        vals = [ts, kind, detail] + [fields[k] for k in fields]
        placeholders = ",".join("?" * len(cols))
        self._db.execute(
            f"INSERT INTO events ({','.join(cols)}) VALUES ({placeholders})", vals
        )

    def recent(self, limit: int = 50, kind: Optional[str] = None) -> list[dict]:
        q = "SELECT * FROM events"
        args: list = []
        if kind:
            q += " WHERE kind = ?"
            args.append(kind)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        cur = self._db.execute(q, args)
        names = [d[0] for d in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]

    def close(self) -> None:
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
