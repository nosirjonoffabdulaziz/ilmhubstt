"""SQLite asosidagi ishlar (job) ombori.

Server qayta ishga tushsa ham ishlar yo'qolmaydi: navbat va holat shu faylda saqlanadi.
Natija matnlari esa har bir ishning o'z papkasidagi JSON faylda turadi.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

ACTIVE_STATUSES = ("converting", "transcribing", "normalizing")
FINAL_STATUSES = ("completed", "failed", "cancelled")

_COLUMNS = (
    "id", "token_hash", "status", "stage", "progress", "error_code", "error_message",
    "filename", "size_bytes", "duration", "options", "created_at", "updated_at",
    "started_at", "finished_at", "cancel_requested", "language", "language_probability",
    "warnings", "processed_seconds", "eta_seconds", "preview", "detail",
)


class JobRepository:
    def __init__(self, db_path: Path, jobs_dir: Path):
        self.db_path = db_path
        self.jobs_dir = jobs_dir
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                token_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                stage TEXT NOT NULL DEFAULT '',
                progress REAL NOT NULL DEFAULT 0,
                error_code TEXT,
                error_message TEXT,
                filename TEXT NOT NULL,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                duration REAL NOT NULL DEFAULT 0,
                options TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                started_at REAL,
                finished_at REAL,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                language TEXT,
                language_probability REAL,
                warnings TEXT NOT NULL DEFAULT '[]',
                processed_seconds REAL NOT NULL DEFAULT 0,
                eta_seconds REAL,
                preview TEXT NOT NULL DEFAULT '[]',
                detail TEXT NOT NULL DEFAULT '{}'
            )"""
        )
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(jobs)").fetchall()}
        if "detail" not in cols:  # eski bazani yangilash
            self._conn.execute("ALTER TABLE jobs ADD COLUMN detail TEXT NOT NULL DEFAULT '{}'")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at)")

    # ---------- yordamchi ----------
    def job_dir(self, job_id: str) -> Path:
        return self.jobs_dir / job_id

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        d = dict(row)
        for key, default in (("options", {}), ("warnings", []), ("preview", []), ("detail", {})):
            try:
                d[key] = json.loads(d.get(key) or "null") or default
            except json.JSONDecodeError:
                d[key] = default
        return d

    # ---------- CRUD ----------
    def create(self, job_id: str, token_hash: str, filename: str, size_bytes: int,
               duration: float, options: dict) -> dict:
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT INTO jobs (id, token_hash, status, stage, filename, size_bytes, duration, options, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (job_id, token_hash, "queued", "queued", filename, size_bytes, duration,
                 json.dumps(options, ensure_ascii=False), now, now),
            )
        return self.get(job_id)  # type: ignore[return-value]

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._decode(row)

    def update(self, job_id: str, **fields: Any) -> None:
        if not fields:
            return
        for key in fields:
            if key not in _COLUMNS:
                raise KeyError(key)
        for key in ("options", "warnings", "preview", "detail"):
            if key in fields and not isinstance(fields[key], str):
                fields[key] = json.dumps(fields[key], ensure_ascii=False)
        fields["updated_at"] = time.time()
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._lock:
            self._conn.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), job_id))

    def add_warning(self, job_id: str, code: str) -> None:
        with self._lock:
            job = self.get(job_id)
            if not job:
                return
            warnings = job["warnings"]
            if code not in warnings:
                warnings.append(code)
                self.update(job_id, warnings=warnings)

    def claim_next(self) -> dict | None:
        """Navbatdagi eng eski ishni atomik tarzda olish."""
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM jobs WHERE status='queued' AND cancel_requested=0 ORDER BY created_at LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            now = time.time()
            self._conn.execute(
                "UPDATE jobs SET status='converting', stage='converting', started_at=COALESCE(started_at, ?), "
                "updated_at=? WHERE id=? AND status='queued'",
                (now, now, row["id"]),
            )
            return self.get(row["id"])

    def queue_position(self, job_id: str) -> int | None:
        with self._lock:
            job = self.get(job_id)
            if not job or job["status"] != "queued":
                return None
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM jobs WHERE status='queued' AND created_at < ?",
                (job["created_at"],),
            ).fetchone()
            return int(row["n"]) + 1

    def count_status(self, *statuses: str) -> int:
        q = ",".join("?" for _ in statuses)
        with self._lock:
            row = self._conn.execute(f"SELECT COUNT(*) AS n FROM jobs WHERE status IN ({q})", statuses).fetchone()
        return int(row["n"])

    def requeue_interrupted(self) -> list[str]:
        """Server to'satdan to'xtagan bo'lsa, yarim qolgan ishlarni navbatga qaytarish."""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT id FROM jobs WHERE status IN ({','.join('?' for _ in ACTIVE_STATUSES)})",
                ACTIVE_STATUSES,
            ).fetchall()
            ids = [r["id"] for r in rows]
            for job_id in ids:
                self.update(job_id, status="queued", stage="queued")
        return ids

    def expired(self, older_than: float) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM jobs WHERE created_at < ? AND status NOT IN (?,?,?,?)",
                (older_than, "queued", *ACTIVE_STATUSES),
            ).fetchall()
        return [r["id"] for r in rows]

    def delete(self, job_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        shutil.rmtree(self.job_dir(job_id), ignore_errors=True)

    def close(self) -> None:
        with self._lock:
            self._conn.close()
