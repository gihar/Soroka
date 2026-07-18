"""Миграция updated_at для legacy-БД без этой колонки.

SQLite запрещает ALTER TABLE ... ADD COLUMN с неконстантным DEFAULT
(CURRENT_TIMESTAMP): такая миграция падала на каждом старте и молча
глоталась except: pass. На свежих БД колонка есть из CREATE TABLE, а на
старых прод-БД её не было — первый UPDATE системного шаблона ронял бота
(«no such column: updated_at», инцидент 2026-07-18).
"""

import aiosqlite
import pytest

from src.database.database import Database

_LEGACY_TEMPLATES_TABLE = """
    CREATE TABLE templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        content TEXT NOT NULL,
        is_default BOOLEAN DEFAULT 0,
        created_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
"""


async def _legacy_db(tmp_path) -> str:
    db_path = str(tmp_path / "legacy.db")
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(_LEGACY_TEMPLATES_TABLE)
        await conn.execute(
            "INSERT INTO templates (name, content, is_default) VALUES (?, ?, 1)",
            ("Дейли", "# старый контент"),
        )
        await conn.commit()
    return db_path


async def _columns(db_path: str) -> list[str]:
    async with aiosqlite.connect(db_path) as conn:
        cursor = await conn.execute("PRAGMA table_info(templates)")
        return [row[1] for row in await cursor.fetchall()]


@pytest.mark.asyncio
async def test_init_db_adds_updated_at_to_legacy_table(tmp_path):
    db_path = await _legacy_db(tmp_path)

    db = Database(db_path=db_path)
    await db.init_db()

    assert "updated_at" in await _columns(db_path)


@pytest.mark.asyncio
async def test_migrated_template_can_be_updated(tmp_path):
    """Сценарий инцидента: UPDATE системного шаблона после миграции работает."""
    db_path = await _legacy_db(tmp_path)

    db = Database(db_path=db_path)
    await db.init_db()

    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "UPDATE templates SET content = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE name = ?",
            ("# новый контент", "Дейли"),
        )
        await conn.commit()
        cursor = await conn.execute(
            "SELECT content, updated_at FROM templates WHERE name = ?", ("Дейли",)
        )
        content, updated_at = await cursor.fetchone()

    assert content == "# новый контент"
    assert updated_at is not None
