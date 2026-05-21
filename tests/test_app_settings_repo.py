"""Tests for AppSettingsRepository."""
import pytest
from src.exceptions.configuration import AdminConfigurationError


@pytest.mark.asyncio
async def test_get_returns_none_for_missing_key(app_settings_repo):
    result = await app_settings_repo.get("nonexistent_key")
    assert result is None


@pytest.mark.asyncio
async def test_set_inserts_new_row(app_settings_repo):
    await app_settings_repo.set("custom_key", "custom_value", admin_id=42)
    result = await app_settings_repo.get("custom_key")
    assert result == "custom_value"


@pytest.mark.asyncio
async def test_set_upserts_existing_row(app_settings_repo):
    await app_settings_repo.set("custom_key", "first", admin_id=42)
    await app_settings_repo.set("custom_key", "second", admin_id=43)
    result = await app_settings_repo.get("custom_key")
    assert result == "second"


@pytest.mark.asyncio
async def test_get_active_model_key_returns_none_initially(app_settings_repo, test_db):
    """Empty DB has no enabled presets, so init_db skips seeding."""
    result = await app_settings_repo.get_active_model_key()
    assert result is None


@pytest.mark.asyncio
async def test_set_active_model_key_rejects_missing_preset(app_settings_repo):
    with pytest.raises(AdminConfigurationError):
        await app_settings_repo.set_active_model_key("does_not_exist", admin_id=42)


@pytest.mark.asyncio
async def test_set_active_model_key_rejects_disabled_preset(app_settings_repo, test_db):
    import aiosqlite
    async with aiosqlite.connect(test_db.db_path) as db:
        await db.execute(
            "INSERT INTO model_presets (key, name, model, base_url, is_enabled) "
            "VALUES (?, ?, ?, ?, 0)",
            ("disabled_key", "Disabled", "m", "u"),
        )
        await db.commit()

    with pytest.raises(AdminConfigurationError):
        await app_settings_repo.set_active_model_key("disabled_key", admin_id=42)


@pytest.mark.asyncio
async def test_set_active_model_key_accepts_enabled_preset(app_settings_repo, test_db):
    import aiosqlite
    async with aiosqlite.connect(test_db.db_path) as db:
        await db.execute(
            "INSERT INTO model_presets (key, name, model, base_url, is_enabled) "
            "VALUES (?, ?, ?, ?, 1)",
            ("ok_key", "OK", "m", "u"),
        )
        await db.commit()

    await app_settings_repo.set_active_model_key("ok_key", admin_id=42)
    assert await app_settings_repo.get_active_model_key() == "ok_key"
