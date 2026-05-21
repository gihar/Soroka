"""Resolution of the active model preset at processing time."""
import pytest
from src.exceptions.configuration import AdminConfigurationError


@pytest.mark.asyncio
async def test_resolve_active_preset_returns_dict(test_db, app_settings_repo):
    """Helper resolves the active preset to a dict when configured correctly."""
    from src.database.model_preset_repo import ModelPresetRepository
    from src.services.processing.llm_generation import resolve_active_preset

    preset_repo = ModelPresetRepository(test_db)
    await preset_repo.upsert(
        key="active", name="Active", model="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
    )
    await app_settings_repo.set_active_model_key("active", admin_id=42)

    preset = await resolve_active_preset(
        app_settings_repo=app_settings_repo,
        preset_repo=preset_repo,
    )
    assert preset["key"] == "active"
    assert preset["model"] == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_resolve_active_preset_raises_when_unset(test_db, app_settings_repo):
    from src.database.model_preset_repo import ModelPresetRepository
    from src.services.processing.llm_generation import resolve_active_preset

    preset_repo = ModelPresetRepository(test_db)
    with pytest.raises(AdminConfigurationError):
        await resolve_active_preset(
            app_settings_repo=app_settings_repo,
            preset_repo=preset_repo,
        )


@pytest.mark.asyncio
async def test_resolve_active_preset_raises_when_disabled(test_db, app_settings_repo):
    """If the active preset has been disabled out-of-band, raise."""
    import aiosqlite
    from src.database.model_preset_repo import ModelPresetRepository
    from src.services.processing.llm_generation import resolve_active_preset

    preset_repo = ModelPresetRepository(test_db)
    await preset_repo.upsert(
        key="active", name="A", model="m", base_url="u",
    )
    await app_settings_repo.set_active_model_key("active", admin_id=42)

    # Disable via direct SQL to bypass the guard
    async with aiosqlite.connect(test_db.db_path) as db:
        await db.execute(
            "UPDATE model_presets SET is_enabled = 0 WHERE key = 'active'"
        )
        await db.commit()

    with pytest.raises(AdminConfigurationError):
        await resolve_active_preset(
            app_settings_repo=app_settings_repo,
            preset_repo=preset_repo,
        )
