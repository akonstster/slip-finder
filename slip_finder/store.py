"""SQLite-хранилище слипов. Переживает удаление логов ARCUS (NDAYS в cashreg.ini)."""
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from .parser import Slip, KIND_LABELS

SCHEMA = """
CREATE TABLE IF NOT EXISTS slips (
    key        TEXT PRIMARY KEY,
    file       TEXT NOT NULL,
    ts         INTEGER NOT NULL,
    kind       TEXT NOT NULL,
    op_raw     TEXT NOT NULL,
    rc         TEXT NOT NULL,
    approved   INTEGER NOT NULL,
    pan_mask   TEXT NOT NULL,
    last4      TEXT NOT NULL,
    tid        TEXT NOT NULL,
    auth_code  TEXT NOT NULL,
    card_type  TEXT NOT NULL,
    status     TEXT NOT NULL,
    amount_kop INTEGER NOT NULL,
    rrn        TEXT NOT NULL,
    receipt_no TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS slips_ts ON slips(ts);
CREATE TABLE IF NOT EXISTS files (
    name  TEXT PRIMARY KEY,
    size  INTEGER NOT NULL,
    mtime REAL NOT NULL
);
"""

COLUMNS = ["key", "file", "ts", "kind", "op_raw", "rc", "approved", "pan_mask", "last4",
           "tid", "auth_code", "card_type", "status", "amount_kop", "rrn", "receipt_no"]

TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")  # точка занята суммой: 2.00
AMOUNT_RE = re.compile(r"^\d+([.,]\d{1,2})?$")
TIME_WINDOW_MIN = 15
# 2: ключ записи = имя файла (раньше RRN, и возврат затирал оплату)
# 3: номер чека (receipt_no)
SCHEMA_VERSION = 3


class Store:
    def __init__(self, path: Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            if self._db.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION:
                # Логи ARCUS ещё на диске: проще переиндексировать, чем мигрировать
                self._db.executescript("DROP TABLE IF EXISTS slips; DROP TABLE IF EXISTS files;")
                self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self._db.executescript(SCHEMA)

    # --- индексация ---

    def file_state(self) -> dict[str, tuple[int, float]]:
        with self._lock:
            rows = self._db.execute("SELECT name, size, mtime FROM files").fetchall()
        return {r["name"]: (r["size"], r["mtime"]) for r in rows}

    def save(self, name: str, size: int, mtime: float, slip: Slip | None):
        with self._lock, self._db:
            if slip is not None:
                d = slip.as_dict()
                d["approved"] = int(d["approved"])
                # Файл мог быть недописан в прошлый раз: убираем его старую запись
                self._db.execute("DELETE FROM slips WHERE file = ?", (name,))
                self._db.execute(
                    f"INSERT OR REPLACE INTO slips ({', '.join(COLUMNS)}) "
                    f"VALUES ({', '.join('?' * len(COLUMNS))})",
                    [d[c] for c in COLUMNS],
                )
            self._db.execute(
                "INSERT OR REPLACE INTO files (name, size, mtime) VALUES (?, ?, ?)",
                (name, size, mtime),
            )

    def stats(self) -> dict:
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*) AS n, MIN(ts) AS first, MAX(ts) AS last FROM slips"
            ).fetchone()
        return {"count": row["n"], "first_ts": row["first"], "last_ts": row["last"]}

    # --- поиск ---

    def search(self, q: str, ts_from: int | None, ts_to: int | None, limit: int = 200) -> list[dict]:
        sql = "SELECT * FROM slips WHERE 1=1"
        params: list = []
        if ts_from is not None:
            sql += " AND ts >= ?"
            params.append(ts_from)
        if ts_to is not None:
            sql += " AND ts < ?"
            params.append(ts_to)
        sql += " ORDER BY ts DESC"
        with self._lock:
            rows = [dict(r) for r in self._db.execute(sql, params).fetchall()]

        tokens = q.lower().split()
        result = []
        for r in rows:
            if all(_matches(r, t) for t in tokens):
                r["approved"] = bool(r["approved"])
                r["kind_label"] = KIND_LABELS.get(r["kind"], r["kind"])
                result.append(r)
                if len(result) >= limit:
                    break
        return result


def _matches(r: dict, token: str) -> bool:
    m = TIME_RE.match(token)
    if m:
        want = int(m.group(1)) * 60 + int(m.group(2))
        t = datetime.fromtimestamp(r["ts"])
        return abs(t.hour * 60 + t.minute - want) <= TIME_WINDOW_MIN

    if AMOUNT_RE.match(token):
        if round(float(token.replace(",", ".")) * 100) == r["amount_kop"]:
            return True
        if token.isdigit():
            if len(token) == 4 and r["last4"] == token:
                return True
            if len(token) >= 4 and (token in r["auth_code"].lower() or r["rrn"].endswith(token)):
                return True
        return False

    haystack = " ".join([
        r["card_type"], r["auth_code"], r["status"], r["rrn"],
        KIND_LABELS.get(r["kind"], ""),
    ]).lower()
    return token in haystack
