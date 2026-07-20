"""Миграция speaker_mapping/meeting_type для legacy-БД без этих колонок.

Перегенерация из истории пропускает ЭТАП 1 анализа, только если тип встречи и
сопоставление спикеров уже известны. Значения берутся из строки истории — но на
старых прод-БД колонок под них нет. init_db должен добавить их живой миграцией
(nullable, без DEFAULT: NULL = «данных нет»), а не падать на первом чтении.
"""

import aiosqlite
import pytest

from src.database.database import Database

_LEGACY_PROCESSING_HISTORY_TABLE = """
    CREATE TABLE processing_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        file_name TEXT,
        template_id INTEGER,
        llm_provider TEXT,
        transcription_text TEXT,
        result_text TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
"""


async def _legacy_db(tmp_path) -> str:
    db_path = str(tmp_path / "legacy.db")
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(_LEGACY_PROCESSING_HISTORY_TABLE)
        await conn.execute(
            "INSERT INTO processing_history (user_id, file_name, result_text) "
            "VALUES (?, ?, ?)",
            (1, "meeting.mp3", "# старый протокол"),
        )
        await conn.commit()
    return db_path


async def _columns(db_path: str) -> list[str]:
    async with aiosqlite.connect(db_path) as conn:
        cursor = await conn.execute("PRAGMA table_info(processing_history)")
        return [row[1] for row in await cursor.fetchall()]


@pytest.mark.asyncio
async def test_init_db_adds_mapping_columns_to_legacy_table(tmp_path):
    db_path = await _legacy_db(tmp_path)

    db = Database(db_path=db_path)
    await db.init_db()

    columns = await _columns(db_path)
    assert "speaker_mapping" in columns
    assert "meeting_type" in columns


@pytest.mark.asyncio
async def test_migrated_history_row_carries_mapping(tmp_path):
    """Сценарий перегенерации: запись истории пишет и отдаёт новые поля."""
    db_path = await _legacy_db(tmp_path)

    db = Database(db_path=db_path)
    await db.init_db()

    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "UPDATE processing_history SET speaker_mapping = ?, meeting_type = ? "
            "WHERE file_name = ?",
            ('{"SPEAKER_00": "Иван"}', "daily", "meeting.mp3"),
        )
        await conn.commit()
        cursor = await conn.execute(
            "SELECT speaker_mapping, meeting_type FROM processing_history "
            "WHERE file_name = ?",
            ("meeting.mp3",),
        )
        speaker_mapping, meeting_type = await cursor.fetchone()

    assert speaker_mapping == '{"SPEAKER_00": "Иван"}'
    assert meeting_type == "daily"


@pytest.mark.asyncio
async def test_init_db_mapping_migration_is_idempotent(tmp_path):
    """Повторный старт на уже мигрированной БД не падает и не плодит колонки."""
    db_path = await _legacy_db(tmp_path)

    db = Database(db_path=db_path)
    await db.init_db()
    await db.init_db()

    columns = await _columns(db_path)
    assert columns.count("speaker_mapping") == 1
    assert columns.count("meeting_type") == 1
