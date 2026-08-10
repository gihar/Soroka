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


# ------------------------------------------------- резервный пресет (автовозврат)


async def _seed_enabled_preset(test_db, key, name="Preset"):
    """Включённый пресет в базе — минимум, который принимает валидация ключей."""
    import aiosqlite
    async with aiosqlite.connect(test_db.db_path) as db:
        await db.execute(
            "INSERT INTO model_presets (key, name, model, base_url, is_enabled) "
            "VALUES (?, ?, ?, ?, 1)",
            (key, name, "m", "u"),
        )
        await db.commit()


@pytest.mark.asyncio
async def test_fallback_model_key_is_unset_by_default(app_settings_repo):
    """Резерв не подразумевается: без явной настройки автовозврату некуда идти."""
    assert await app_settings_repo.get_fallback_model_key() is None


@pytest.mark.asyncio
async def test_set_fallback_model_key_stores_preset(app_settings_repo, test_db):
    await _seed_enabled_preset(test_db, "reserve")

    await app_settings_repo.set_fallback_model_key("reserve", admin_id=42)
    assert await app_settings_repo.get_fallback_model_key() == "reserve"


@pytest.mark.asyncio
async def test_set_fallback_model_key_rejects_missing_preset(app_settings_repo):
    """Резерв, которого нет, — обещание без адреса: ловим при настройке, не в стену."""
    with pytest.raises(AdminConfigurationError):
        await app_settings_repo.set_fallback_model_key("does_not_exist", admin_id=42)


@pytest.mark.asyncio
async def test_set_fallback_model_key_rejects_disabled_preset(app_settings_repo, test_db):
    import aiosqlite
    async with aiosqlite.connect(test_db.db_path) as db:
        await db.execute(
            "INSERT INTO model_presets (key, name, model, base_url, is_enabled) "
            "VALUES (?, ?, ?, ?, 0)",
            ("disabled_reserve", "Disabled", "m", "u"),
        )
        await db.commit()

    with pytest.raises(AdminConfigurationError):
        await app_settings_repo.set_fallback_model_key("disabled_reserve", admin_id=42)


@pytest.mark.asyncio
async def test_clear_fallback_model_key(app_settings_repo, test_db):
    """Резерв снимается: администратор может остаться без автовозврата осознанно."""
    await _seed_enabled_preset(test_db, "reserve")
    await app_settings_repo.set_fallback_model_key("reserve", admin_id=42)

    await app_settings_repo.clear_fallback_model_key(admin_id=42)
    assert await app_settings_repo.get_fallback_model_key() is None


@pytest.mark.asyncio
async def test_automatic_switch_leaves_the_journal_without_an_author(
    app_settings_repo, test_db
):
    """Автовозврат делает не человек: в журнале остаётся пусто, а не чужое имя.

    Проверяем и то, что запись без автора читается дальше: `updated_by` в коде
    нигде не форматируется, а сама база сеет `active_model_key` с NULL при
    старте — пустой автор для этой настройки состояние штатное.
    """
    import aiosqlite

    await _seed_enabled_preset(test_db, "qwen")
    await _seed_enabled_preset(test_db, "reserve")
    await app_settings_repo.set_active_model_key("qwen", admin_id=42)

    await app_settings_repo.set_active_model_key("reserve", admin_id=None)

    assert await app_settings_repo.get_active_model_key() == "reserve"
    async with aiosqlite.connect(test_db.db_path) as db:
        cursor = await db.execute(
            "SELECT updated_by FROM app_settings WHERE key = 'active_model_key'"
        )
        row = await cursor.fetchone()
    assert row[0] is None, "автовозврат не должен оставлять в журнале админа 42"


@pytest.mark.asyncio
async def test_active_model_key_survives_fallback_changes(app_settings_repo, test_db):
    """Две настройки живут раздельно: резерв не трогает активный пресет."""
    await _seed_enabled_preset(test_db, "active")
    await _seed_enabled_preset(test_db, "reserve")
    await app_settings_repo.set_active_model_key("active", admin_id=42)

    await app_settings_repo.set_fallback_model_key("reserve", admin_id=42)

    assert await app_settings_repo.get_active_model_key() == "active"
    assert await app_settings_repo.get_fallback_model_key() == "reserve"
