"""Guards: cannot delete or disable the active preset."""
import pytest

from src.exceptions.configuration import ActivePresetDeletionError


async def _seed_preset(repo, key="active", enabled=True):
    await repo.upsert(key=key, name=key, model="m", base_url="u")
    if not enabled:
        await repo.update_field(key, "is_enabled", 0)


@pytest.mark.asyncio
async def test_delete_active_preset_raises(test_db, app_settings_repo):
    from src.database.model_preset_repo import ModelPresetRepository
    repo = ModelPresetRepository(test_db)
    await _seed_preset(repo, key="active")
    await app_settings_repo.set_active_model_key("active", admin_id=42)

    with pytest.raises(ActivePresetDeletionError):
        await repo.delete("active")


@pytest.mark.asyncio
async def test_delete_inactive_preset_succeeds(test_db, app_settings_repo):
    from src.database.model_preset_repo import ModelPresetRepository
    repo = ModelPresetRepository(test_db)
    await _seed_preset(repo, key="active")
    await _seed_preset(repo, key="other")
    await app_settings_repo.set_active_model_key("active", admin_id=42)

    result = await repo.delete("other")
    assert result is True


@pytest.mark.asyncio
async def test_disable_active_preset_raises(test_db, app_settings_repo):
    from src.database.model_preset_repo import ModelPresetRepository
    repo = ModelPresetRepository(test_db)
    await _seed_preset(repo, key="active")
    await app_settings_repo.set_active_model_key("active", admin_id=42)

    with pytest.raises(ActivePresetDeletionError):
        await repo.update_field("active", "is_enabled", 0)


@pytest.mark.asyncio
async def test_update_other_fields_on_active_preset_allowed(test_db, app_settings_repo):
    """update_field setting non-is_enabled fields (or is_enabled=1) on the active preset is fine."""
    from src.database.model_preset_repo import ModelPresetRepository
    repo = ModelPresetRepository(test_db)
    await _seed_preset(repo, key="active")
    await app_settings_repo.set_active_model_key("active", admin_id=42)

    # Setting other fields is OK
    ok = await repo.update_field("active", "name", "Renamed")
    assert ok is True

    # Setting is_enabled to 1 (already 1) is OK
    ok = await repo.update_field("active", "is_enabled", 1)
    assert ok is True
