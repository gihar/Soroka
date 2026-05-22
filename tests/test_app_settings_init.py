"""Tests for app_settings table creation and seed during init_db."""
import aiosqlite
import pytest


@pytest.mark.asyncio
async def test_app_settings_table_exists(test_db):
    """init_db creates app_settings table."""
    async with aiosqlite.connect(test_db.db_path) as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='app_settings'"
        )
        row = await cursor.fetchone()
        assert row is not None, "app_settings table was not created"


@pytest.mark.asyncio
async def test_app_settings_seed_skipped_when_no_presets(test_db):
    """When no enabled presets exist, active_model_key is NOT seeded."""
    async with aiosqlite.connect(test_db.db_path) as db:
        cursor = await db.execute(
            "SELECT value FROM app_settings WHERE key = 'active_model_key'"
        )
        row = await cursor.fetchone()
        assert row is None, "Should not seed when no enabled presets"


@pytest.mark.asyncio
async def test_app_settings_seeds_first_enabled_preset(tmp_path):
    """When init_db runs and presets exist, the first enabled preset key is seeded."""
    from src.database.database import Database
    db_path = str(tmp_path / "test.db")
    db = Database(db_path=db_path)
    await db.init_db()

    # Insert enabled preset manually, then re-run init_db (idempotent)
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO model_presets (key, name, model, base_url, is_enabled) VALUES (?, ?, ?, ?, 1)",
            ("seed_key", "Seed Model", "gpt-4o-mini", "https://api.openai.com/v1"),
        )
        await conn.commit()

    await db.init_db()  # second call should seed active_model_key

    async with aiosqlite.connect(db_path) as conn:
        cursor = await conn.execute(
            "SELECT value FROM app_settings WHERE key = 'active_model_key'"
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "seed_key"


@pytest.mark.asyncio
async def test_app_settings_seed_is_idempotent(tmp_path):
    """Re-running init_db does not overwrite an existing active_model_key."""
    from src.database.database import Database
    db_path = str(tmp_path / "test.db")
    db = Database(db_path=db_path)
    await db.init_db()

    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO model_presets (key, name, model, base_url, is_enabled) VALUES (?, ?, ?, ?, 1)",
            ("first", "First", "m1", "u1"),
        )
        await conn.execute(
            "INSERT INTO model_presets (key, name, model, base_url, is_enabled) VALUES (?, ?, ?, ?, 1)",
            ("second", "Second", "m2", "u2"),
        )
        await conn.execute(
            "INSERT INTO app_settings (key, value, updated_by) VALUES ('active_model_key', 'second', 42)"
        )
        await conn.commit()

    await db.init_db()

    async with aiosqlite.connect(db_path) as conn:
        cursor = await conn.execute(
            "SELECT value, updated_by FROM app_settings WHERE key = 'active_model_key'"
        )
        row = await cursor.fetchone()
        assert row[0] == "second"
        assert row[1] == 42
