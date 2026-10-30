"""Atomic, token-aware sliding-window limiter backed by SQLite."""

import asyncio
import math
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from config import DATABASE_PATH, TOKEN_BUDGET, WINDOW_SECONDS


@dataclass(frozen=True)
class Reservation:
    admitted: bool
    row_id: int | None
    retry_after: float
    used_tokens: int


class RateLimiter:
    def __init__(
        self,
        db_path: str | Path = DATABASE_PATH,
        budget: int = TOKEN_BUDGET,
        window_seconds: int = WINDOW_SECONDS,
    ) -> None:
        if budget <= 0 or window_seconds <= 0:
            raise ValueError("budget and window_seconds must be positive")
        self.db_path = str(db_path)
        self.budget = budget
        self.window_seconds = window_seconds
        self._lock = asyncio.Lock()

    async def reserve(
        self, api_key: str, tokens: int, *, now: float | None = None
    ) -> Reservation:
        if not api_key or tokens <= 0:
            raise ValueError("api_key and positive tokens are required")
        async with self._lock:
            return await asyncio.to_thread(
                self._reserve_sync,
                api_key,
                tokens,
                time.time() if now is None else now,
            )

    async def reconcile(
        self, row_id: int, actual_tokens: int, *, now: float | None = None
    ) -> None:
        if actual_tokens < 0:
            raise ValueError("actual_tokens cannot be negative")
        async with self._lock:
            await asyncio.to_thread(
                self._reconcile_sync,
                row_id,
                actual_tokens,
                time.time() if now is None else now,
            )

    def _connect(self) -> sqlite3.Connection:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                api_key TEXT NOT NULL,
                ts REAL NOT NULL,
                tokens INTEGER NOT NULL CHECK (tokens >= 0)
            )
            """
        )
        return connection

    def _reserve_sync(self, api_key: str, tokens: int, now: float) -> Reservation:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cutoff = now - self.window_seconds
            connection.execute("DELETE FROM usage WHERE ts <= ?", (cutoff,))
            rows = connection.execute(
                "SELECT ts, tokens FROM usage WHERE api_key = ? AND ts > ? ORDER BY ts",
                (api_key, cutoff),
            ).fetchall()
            used = sum(int(row[1]) for row in rows)
            if used + tokens > self.budget:
                release_needed = used + tokens - self.budget
                released = 0
                retry_after = float(self.window_seconds)
                for timestamp, row_tokens in rows:
                    released += int(row_tokens)
                    if released >= release_needed:
                        retry_after = max(
                            0.0, float(timestamp) + self.window_seconds - now
                        )
                        break
                connection.commit()
                return Reservation(
                    admitted=False,
                    row_id=None,
                    retry_after=max(1.0, math.ceil(retry_after)),
                    used_tokens=used,
                )

            cursor = connection.execute(
                "INSERT INTO usage (api_key, ts, tokens) VALUES (?, ?, ?)",
                (api_key, now, tokens),
            )
            row_id = int(cursor.lastrowid)
            connection.commit()
            return Reservation(
                admitted=True,
                row_id=row_id,
                retry_after=0.0,
                used_tokens=used + tokens,
            )
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _reconcile_sync(
        self, row_id: int, actual_tokens: int, now: float
    ) -> None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM usage WHERE ts <= ?",
                (now - self.window_seconds,),
            )
            cursor = connection.execute(
                "UPDATE usage SET tokens = ? WHERE id = ?",
                (actual_tokens, row_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Reservation {row_id} does not exist in the window")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
