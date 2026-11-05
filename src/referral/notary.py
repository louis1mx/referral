"""SQLite storage and the Notary: an append-only, hash-chained, signed log.

`jobs` and `matches` hold current state for fast lookups. `notary_log` is the evidence:
contracts, forecasts, deliveries, verdicts and refused attempts. Triggers stop updates
and deletes, each entry hashes the previous one, and each entry carries an HMAC made
with the acting agent's key, so `verify_chain` catches edits made behind our back.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from collections.abc import Callable

SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY, name TEXT UNIQUE, role TEXT, owner TEXT, model TEXT,
    key TEXT, domains TEXT, price REAL, typical_seconds REAL, declared_success REAL,
    created_at REAL
);
CREATE TABLE IF NOT EXISTS matches (
    match_id TEXT PRIMARY KEY, buyer_id TEXT, spec TEXT, band TEXT, candidate_id TEXT,
    action TEXT, strategy TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY, buyer_id TEXT, worker_id TEXT, worker_model TEXT,
    parent_job_id TEXT, match_id TEXT, spec TEXT, band TEXT, canary INTEGER, canary_salt TEXT,
    status TEXT, trial INTEGER, self_dealing INTEGER, created_at REAL, deadline_at REAL,
    budget REAL, price REAL, prediction TEXT, delivery TEXT, verdict TEXT, outcome INTEGER,
    cost REAL, reported_cost REAL, elapsed REAL, attributed TEXT, settled_at REAL
);
CREATE TABLE IF NOT EXISTS notary_log (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, job_id TEXT, actor TEXT,
    payload TEXT, prev_hash TEXT, hash TEXT, sig TEXT
);
CREATE TRIGGER IF NOT EXISTS notary_no_update BEFORE UPDATE ON notary_log
BEGIN SELECT RAISE(ABORT, 'notary_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS notary_no_delete BEFORE DELETE ON notary_log
BEGIN SELECT RAISE(ABORT, 'notary_log is append-only'); END;
"""

JSON_COLUMNS = {"spec", "domains", "prediction", "delivery", "verdict", "attributed"}
# Columns added after runs were already recorded; older databases get them on open so they
# can still be audited.
ADDED_COLUMNS = {("agents", "declared_success"): "REAL", ("jobs", "reported_cost"): "REAL"}
GENESIS = "0" * 64


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


class Store:
    def __init__(self, path: str = ":memory:"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        for (table, col), kind in ADDED_COLUMNS.items():
            have = {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}
            if col not in have:
                with self.db:
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {kind}")

    def _encode(self, row: dict) -> dict:
        return {k: canonical(v) if k in JSON_COLUMNS and v is not None else v
                for k, v in row.items()}

    def _decode(self, row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        d = dict(row)
        for k in JSON_COLUMNS & d.keys():
            if d[k] is not None:
                d[k] = json.loads(d[k])
        return d

    def insert(self, table: str, row: dict) -> None:
        row = self._encode(row)
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        with self.db:
            self.db.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(row.values()))

    def update(self, table: str, key_col: str, key: str, fields: dict) -> None:
        fields = self._encode(fields)
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self.db:
            self.db.execute(f"UPDATE {table} SET {sets} WHERE {key_col} = ?",
                            [*fields.values(), key])

    def get(self, table: str, key_col: str, key: str) -> dict | None:
        cur = self.db.execute(f"SELECT * FROM {table} WHERE {key_col} = ?", (key,))
        return self._decode(cur.fetchone())

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        return [self._decode(r) for r in self.db.execute(sql, params).fetchall()]

    def count(self, table: str) -> int:
        return self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class Notary:
    def __init__(self, store: Store, key_of: Callable[[str], str]):
        self.store = store
        self.key_of = key_of

    def head(self) -> str:
        row = self.store.db.execute("SELECT hash FROM notary_log ORDER BY seq DESC LIMIT 1").fetchone()
        return row[0] if row else GENESIS

    @staticmethod
    def _hash(prev: str, ts: float, kind: str, job_id: str | None, actor: str, payload: dict) -> str:
        body = canonical({"ts": ts, "kind": kind, "job_id": job_id, "actor": actor, "payload": payload})
        return hashlib.sha256(f"{prev}|{body}".encode()).hexdigest()

    def _sign(self, actor: str, digest: str) -> str:
        return hmac.new(self.key_of(actor).encode(), digest.encode(), hashlib.sha256).hexdigest()

    def append(self, kind: str, actor: str, payload: dict, job_id: str | None, ts: float) -> dict:
        prev = self.head()
        digest = self._hash(prev, ts, kind, job_id, actor, payload)
        entry = {"ts": ts, "kind": kind, "job_id": job_id, "actor": actor, "payload": payload,
                 "prev_hash": prev, "hash": digest, "sig": self._sign(actor, digest)}
        self.store.insert("notary_log", {**entry, "payload": canonical(payload)})
        return entry

    def entries(self, job_id: str | None = None) -> list[dict]:
        sql = "SELECT * FROM notary_log"
        params: tuple = ()
        if job_id:
            sql += " WHERE job_id = ?"
            params = (job_id,)
        rows = self.store.query(sql + " ORDER BY seq", params)
        for r in rows:
            r["payload"] = json.loads(r["payload"])
        return rows

    def verify_chain(self) -> tuple[bool, list[str]]:
        problems = []
        prev = GENESIS
        for e in self.entries():
            digest = self._hash(prev, e["ts"], e["kind"], e["job_id"], e["actor"], e["payload"])
            if e["prev_hash"] != prev:
                problems.append(f"entry {e['seq']}: chain broken (prev_hash mismatch)")
            if e["hash"] != digest:
                problems.append(f"entry {e['seq']}: contents changed after logging")
            elif not hmac.compare_digest(e["sig"], self._sign(e["actor"], digest)):
                problems.append(f"entry {e['seq']}: bad signature for {e['actor']}")
            prev = e["hash"]
        return (not problems, problems)
