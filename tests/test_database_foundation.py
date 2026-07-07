"""Фундамент миграции на репозитории (#26): connect(), миграции схемы в init_db."""
import aiosqlite
import pytest

from src.database.database import Database


async def test_connect_yields_row_connection(test_db):
    """Database.connect() даёт соединение с row_factory=Row, готовое к запросам."""
    async with test_db.connect() as conn:
        cursor = await conn.execute("SELECT 1 AS answer")
        row = await cursor.fetchone()
        assert row["answer"] == 1
        assert isinstance(row, aiosqlite.Row)


async def _column_names(db: Database, table: str) -> set:
    async with db.connect() as conn:
        cursor = await conn.execute(f"PRAGMA table_info({table})")
        return {row["name"] for row in await cursor.fetchall()}


async def test_init_db_upgrades_legacy_schema(tmp_path):
    """init_db приводит старую БД (без saved_participants/updated_at) к актуальной схеме."""
    db_path = str(tmp_path / "legacy.db")
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, telegram_id INTEGER UNIQUE NOT NULL)"
        )
        await conn.execute(
            "CREATE TABLE templates (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "name TEXT NOT NULL, content TEXT NOT NULL)"
        )
        await conn.commit()

    db = Database(db_path=db_path)
    await db.init_db()

    assert "saved_participants" in await _column_names(db, "users")
    assert "updated_at" in await _column_names(db, "templates")


async def test_init_db_fresh_schema_is_complete(test_db):
    """После init_db на пустой БД схема актуальна — репозиториям не нужно самолечение."""
    assert "saved_participants" in await _column_names(test_db, "users")
    assert "updated_at" in await _column_names(test_db, "templates")
