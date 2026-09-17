from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite
# Compatibility helper for aiosqlite
if not hasattr(aiosqlite.Connection, "execute_fetchone"):
    async def _execute_fetchone(self, sql, parameters=()):
        async with self.execute(sql, parameters) as cursor:
            return await cursor.fetchone()

    aiosqlite.Connection.execute_fetchone = _execute_fetchone


class Database:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def connect(self):
        db = await aiosqlite.connect(self.path.as_posix(), timeout=30)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("PRAGMA journal_mode = WAL")
        await db.execute("PRAGMA busy_timeout = 30000")
        try:
            yield db
        finally:
            await db.close()

    async def init(self) -> None:
        async with self.connect() as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL UNIQUE,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    is_allowed INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tweets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'available'
                        CHECK(status IN ('available','assigned','used')),
                    assigned_at INTEGER,
                    used_at INTEGER,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS assignments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tweet_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'assigned'
                        CHECK(status IN ('assigned','used','released')),
                    assigned_at INTEGER NOT NULL,
                    used_at INTEGER,
                    released_at INTEGER,
                    FOREIGN KEY(tweet_id) REFERENCES tweets(id) ON DELETE RESTRICT,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_tweets_status ON tweets(status);
                CREATE INDEX IF NOT EXISTS idx_tweets_text ON tweets(text);
                CREATE INDEX IF NOT EXISTS idx_assignments_user ON assignments(user_id);
                CREATE INDEX IF NOT EXISTS idx_assignments_tweet ON assignments(tweet_id);
                CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

                CREATE UNIQUE INDEX IF NOT EXISTS uq_active_tweet_assignment
                    ON assignments(tweet_id)
                    WHERE status = 'assigned';

                CREATE UNIQUE INDEX IF NOT EXISTS uq_active_user_assignment
                    ON assignments(user_id)
                    WHERE status = 'assigned';
                """
            )
            await db.commit()

    async def upsert_user(
        self,
        telegram_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        force_allowed: bool | None = None,
    ) -> None:
        now = int(time.time())
        async with self.connect() as db:
            row = await db.execute_fetchone(
                "SELECT id, is_allowed FROM users WHERE telegram_id = ?",
                (telegram_id,),
            )
            if row:
                if force_allowed is None:
                    await db.execute(
                        """
                        UPDATE users
                        SET username=?, first_name=?, last_name=?, updated_at=?
                        WHERE telegram_id=?
                        """,
                        (username, first_name, last_name, now, telegram_id),
                    )
                else:
                    await db.execute(
                        """
                        UPDATE users
                        SET username=?, first_name=?, last_name=?, is_allowed=?, updated_at=?
                        WHERE telegram_id=?
                        """,
                        (username, first_name, last_name, int(force_allowed), now, telegram_id),
                    )
            else:
                await db.execute(
                    """
                    INSERT INTO users
                        (telegram_id, username, first_name, last_name, is_allowed, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (telegram_id, username, first_name, last_name, int(bool(force_allowed)), now, now),
                )
            await db.commit()

    async def set_allowed(self, telegram_id: int, allowed: bool) -> bool:
        now = int(time.time())
        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO users(telegram_id, is_allowed, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    is_allowed=excluded.is_allowed,
                    updated_at=excluded.updated_at
                """,
                (telegram_id, int(allowed), now, now),
            )
            await db.commit()
            return True

    async def get_user_by_telegram_id(self, telegram_id: int) -> aiosqlite.Row | None:
        async with self.connect() as db:
            return await db.execute_fetchone(
                "SELECT * FROM users WHERE telegram_id=?",
                (telegram_id,),
            )

    async def get_or_create_user_id(self, telegram_id: int) -> int:
        row = await self.get_user_by_telegram_id(telegram_id)
        if row:
            return int(row["id"])
        raise ValueError("User must be upserted before this operation")

    async def add_tweet(self, text: str) -> int:
        text = text.strip()
        if not text:
            raise ValueError("tweet text is empty")
        now = int(time.time())
        async with self.connect() as db:
            cur = await db.execute(
                "INSERT INTO tweets(text, status, created_at, updated_at) VALUES (?, 'available', ?, ?)",
                (text, now, now),
            )
            await db.commit()
            return int(cur.lastrowid)

    async def add_tweets_bulk(self, texts: list[str]) -> int:
        cleaned = [t.strip() for t in texts if t and t.strip()]
        if not cleaned:
            return 0
        now = int(time.time())
        async with self.connect() as db:
            await db.executemany(
                "INSERT INTO tweets(text, status, created_at, updated_at) VALUES (?, 'available', ?, ?)",
                [(text, now, now) for text in cleaned],
            )
            await db.commit()
        return len(cleaned)

    async def update_tweet(self, tweet_id: int, text: str) -> bool:
        text = text.strip()
        if not text:
            raise ValueError("tweet text is empty")
        now = int(time.time())
        async with self.connect() as db:
            cur = await db.execute(
                "UPDATE tweets SET text=?, updated_at=? WHERE id=?",
                (text, now, tweet_id),
            )
            await db.commit()
            return cur.rowcount > 0

    async def delete_tweet(self, tweet_id: int) -> tuple[bool, str]:
        async with self.connect() as db:
            row = await db.execute_fetchone(
                "SELECT status FROM tweets WHERE id=?",
                (tweet_id,),
            )
            if not row:
                return False, "not_found"
            if row["status"] != "available":
                return False, "not_available"
            await db.execute("DELETE FROM tweets WHERE id=?", (tweet_id,))
            await db.commit()
            return True, "deleted"

    async def assign_for_user(self, telegram_id: int) -> dict[str, Any] | None:
        """Atomically return current assignment or reserve the next available tweet.

        BEGIN IMMEDIATE serializes competing writers in SQLite. The SELECT + UPDATE + INSERT
        therefore happens inside one write transaction, so the same tweet cannot be reserved
        twice by concurrent requests.
        """
        now = int(time.time())
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                user = await db.execute_fetchone(
                    "SELECT * FROM users WHERE telegram_id=?",
                    (telegram_id,),
                )
                if not user or not user["is_allowed"]:
                    await db.rollback()
                    return None

                current = await db.execute_fetchone(
                    """
                    SELECT a.id AS assignment_id, t.id AS tweet_id, t.text,
                           a.assigned_at, a.status AS assignment_status
                    FROM assignments a
                    JOIN tweets t ON t.id = a.tweet_id
                    WHERE a.user_id=? AND a.status='assigned'
                    LIMIT 1
                    """,
                    (user["id"],),
                )
                if current:
                    await db.commit()
                    return dict(current)

                tweet = await db.execute_fetchone(
                    """
                    SELECT id, text FROM tweets
                    WHERE status='available'
                    ORDER BY id ASC
                    LIMIT 1
                    """
                )
                if not tweet:
                    await db.commit()
                    return None

                await db.execute(
                    "UPDATE tweets SET status='assigned', assigned_at=?, updated_at=? WHERE id=? AND status='available'",
                    (now, now, tweet["id"]),
                )
                await db.execute(
                    """
                    INSERT INTO assignments(tweet_id, user_id, status, assigned_at)
                    VALUES (?, ?, 'assigned', ?)
                    """,
                    (tweet["id"], user["id"], now),
                )
                await db.commit()
                return {
                    "assignment_id": None,
                    "tweet_id": tweet["id"],
                    "text": tweet["text"],
                    "assigned_at": now,
                    "assignment_status": "assigned",
                }
            except Exception:
                await db.rollback()
                raise

    async def mark_current_used(self, telegram_id: int) -> dict[str, Any] | None:
        now = int(time.time())
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                row = await db.execute_fetchone(
                    """
                    SELECT a.id AS assignment_id, a.tweet_id, t.text
                    FROM assignments a
                    JOIN users u ON u.id=a.user_id
                    JOIN tweets t ON t.id=a.tweet_id
                    WHERE u.telegram_id=? AND a.status='assigned'
                    LIMIT 1
                    """,
                    (telegram_id,),
                )
                if not row:
                    await db.commit()
                    return None

                await db.execute(
                    "UPDATE assignments SET status='used', used_at=? WHERE id=? AND status='assigned'",
                    (now, row["assignment_id"]),
                )
                await db.execute(
                    "UPDATE tweets SET status='used', used_at=?, updated_at=? WHERE id=? AND status='assigned'",
                    (now, now, row["tweet_id"]),
                )
                await db.commit()
                return dict(row)
            except Exception:
                await db.rollback()
                raise

    async def release_tweet(self, tweet_id: int) -> tuple[bool, str, int | None]:
        now = int(time.time())
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                tweet = await db.execute_fetchone(
                    "SELECT id, status FROM tweets WHERE id=?",
                    (tweet_id,),
                )
                if not tweet:
                    await db.rollback()
                    return False, "not_found", None
                if tweet["status"] != "assigned":
                    await db.rollback()
                    return False, "not_assigned", None

                ass = await db.execute_fetchone(
                    "SELECT id, user_id FROM assignments WHERE tweet_id=? AND status='assigned'",
                    (tweet_id,),
                )
                if not ass:
                    await db.rollback()
                    return False, "assignment_missing", None

                await db.execute(
                    "UPDATE assignments SET status='released', released_at=? WHERE id=? AND status='assigned'",
                    (now, ass["id"]),
                )
                await db.execute(
                    "UPDATE tweets SET status='available', assigned_at=NULL, updated_at=? WHERE id=? AND status='assigned'",
                    (now, tweet_id),
                )
                await db.commit()
                return True, "released", int(ass["user_id"])
            except Exception:
                await db.rollback()
                raise

    async def manual_assign(self, tweet_id: int, telegram_id: int) -> tuple[bool, str]:
        now = int(time.time())
        async with self.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                user = await db.execute_fetchone(
                    "SELECT id, is_allowed FROM users WHERE telegram_id=?",
                    (telegram_id,),
                )
                if not user:
                    await db.rollback()
                    return False, "user_not_found"
                if not user["is_allowed"]:
                    await db.rollback()
                    return False, "user_not_allowed"
                active = await db.execute_fetchone(
                    "SELECT id FROM assignments WHERE user_id=? AND status='assigned'",
                    (user["id"],),
                )
                if active:
                    await db.rollback()
                    return False, "user_has_active_assignment"
                tweet = await db.execute_fetchone(
                    "SELECT id, status FROM tweets WHERE id=?",
                    (tweet_id,),
                )
                if not tweet:
                    await db.rollback()
                    return False, "tweet_not_found"
                if tweet["status"] != "available":
                    await db.rollback()
                    return False, "tweet_not_available"

                await db.execute(
                    "UPDATE tweets SET status='assigned', assigned_at=?, updated_at=? WHERE id=? AND status='available'",
                    (now, now, tweet_id),
                )
                await db.execute(
                    "INSERT INTO assignments(tweet_id, user_id, status, assigned_at) VALUES (?, ?, 'assigned', ?)",
                    (tweet_id, user["id"], now),
                )
                await db.commit()
                return True, "assigned"
            except Exception:
                await db.rollback()
                raise

    async def stats(self) -> dict[str, int]:
        async with self.connect() as db:
            rows = await db.execute_fetchall(
                "SELECT status, COUNT(*) AS c FROM tweets GROUP BY status"
            )
            stats = {"available": 0, "assigned": 0, "used": 0}
            for row in rows:
                stats[row["status"]] = int(row["c"])
            user_count = await db.execute_fetchone("SELECT COUNT(*) AS c FROM users")
            allowed_count = await db.execute_fetchone("SELECT COUNT(*) AS c FROM users WHERE is_allowed=1")
            stats["users"] = int(user_count["c"])
            stats["allowed_users"] = int(allowed_count["c"])
            stats["total"] = stats["available"] + stats["assigned"] + stats["used"]
            return stats

    async def list_available_tweets(self, limit: int = 50) -> list[aiosqlite.Row]:
        async with self.connect() as db:
            return await db.execute_fetchall(
                "SELECT id, text, status FROM tweets WHERE status='available' ORDER BY id ASC LIMIT ?",
                (limit,),
            )

    async def list_assigned_tweets(self, limit: int = 50) -> list[aiosqlite.Row]:
        async with self.connect() as db:
            return await db.execute_fetchall(
                """
                SELECT t.id, t.text, t.status, a.assigned_at, u.telegram_id
                FROM tweets t
                JOIN assignments a ON a.tweet_id=t.id AND a.status='assigned'
                JOIN users u ON u.id=a.user_id
                WHERE t.status='assigned'
                ORDER BY t.id ASC LIMIT ?
                """,
                (limit,),
            )

    async def list_allowed_users(self, limit: int = 50) -> list[aiosqlite.Row]:
        async with self.connect() as db:
            return await db.execute_fetchall(
                """
                SELECT id, telegram_id, username, first_name, last_name, is_allowed
                FROM users WHERE is_allowed=1
                ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            )

    async def list_tweets(self, limit: int = 30, offset: int = 0) -> list[aiosqlite.Row]:
        async with self.connect() as db:
            return await db.execute_fetchall(
                """
                SELECT t.id, t.text, t.status, t.created_at, t.assigned_at, t.used_at,
                       u.telegram_id, u.username, u.first_name
                FROM tweets t
                LEFT JOIN assignments a ON a.tweet_id=t.id AND a.status='assigned'
                LEFT JOIN users u ON u.id=a.user_id
                ORDER BY t.id DESC LIMIT ? OFFSET ?
                """,
                (limit, offset),
            )

    async def search_tweets(self, query: str, limit: int = 20) -> list[aiosqlite.Row]:
        async with self.connect() as db:
            return await db.execute_fetchall(
                """
                SELECT t.id, t.text, t.status,
                       u.telegram_id, u.username, u.first_name
                FROM tweets t
                LEFT JOIN assignments a ON a.tweet_id=t.id AND a.status='assigned'
                LEFT JOIN users u ON u.id=a.user_id
                WHERE CAST(t.id AS TEXT)=? OR t.text LIKE ?
                ORDER BY t.id DESC LIMIT ?
                """,
                (query, f"%{query}%", limit),
            )

    async def search_users(self, query: str, limit: int = 20) -> list[aiosqlite.Row]:
        async with self.connect() as db:
            return await db.execute_fetchall(
                """
                SELECT id, telegram_id, username, first_name, last_name, is_allowed, created_at
                FROM users
                WHERE CAST(telegram_id AS TEXT)=?
                   OR COALESCE(username,'') LIKE ?
                   OR COALESCE(first_name,'') LIKE ?
                   OR COALESCE(last_name,'') LIKE ?
                ORDER BY id DESC LIMIT ?
                """,
                (query, f"%{query}%", f"%{query}%", f"%{query}%", limit),
            )

    async def list_users(self, limit: int = 30, offset: int = 0) -> list[aiosqlite.Row]:
        async with self.connect() as db:
            return await db.execute_fetchall(
                """
                SELECT id, telegram_id, username, first_name, last_name, is_allowed, created_at
                FROM users ORDER BY id DESC LIMIT ? OFFSET ?
                """,
                (limit, offset),
            )

    async def assignment_history_for_user(self, telegram_id: int, limit: int = 30) -> list[aiosqlite.Row]:
        async with self.connect() as db:
            return await db.execute_fetchall(
                """
                SELECT t.id AS tweet_id, t.text, a.status, a.assigned_at, a.used_at, a.released_at
                FROM assignments a
                JOIN users u ON u.id=a.user_id
                JOIN tweets t ON t.id=a.tweet_id
                WHERE u.telegram_id=?
                ORDER BY a.id DESC LIMIT ?
                """,
                (telegram_id, limit),
            )

    async def get_tweet(self, tweet_id: int) -> aiosqlite.Row | None:
        async with self.connect() as db:
            return await db.execute_fetchone("SELECT * FROM tweets WHERE id=?", (tweet_id,))
