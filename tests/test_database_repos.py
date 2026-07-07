"""Tests for database repository pattern."""
import pytest


@pytest.mark.asyncio
async def test_create_and_get_user(user_repo):
    await user_repo.create_user(telegram_id=12345, username="testuser", first_name="Test")
    user = await user_repo.get_user(12345)
    assert user is not None
    assert user["telegram_id"] == 12345
    assert user["username"] == "testuser"


@pytest.mark.asyncio
async def test_get_nonexistent_user(user_repo):
    user = await user_repo.get_user(99999)
    assert user is None


@pytest.mark.asyncio
async def test_update_protocol_output_preference(user_repo):
    await user_repo.create_user(telegram_id=12345)
    await user_repo.update_protocol_output_preference(12345, "file")
    user = await user_repo.get_user(12345)
    assert user["protocol_output_mode"] == "file"


@pytest.mark.asyncio
async def test_create_and_get_template(template_repo):
    template_id = await template_repo.create_template(
        name="Test Template",
        description="A test",
        content="## Title\n{discussion}",
    )
    assert template_id is not None
    template = await template_repo.get_template(template_id)
    assert template["name"] == "Test Template"


@pytest.mark.asyncio
async def test_get_nonexistent_template(template_repo):
    template = await template_repo.get_template(99999)
    assert template is None


@pytest.mark.asyncio
async def test_get_all_templates(template_repo):
    await template_repo.create_template(name="T1", content="c1")
    await template_repo.create_template(name="T2", content="c2")
    templates = await template_repo.get_templates()
    assert len(templates) >= 2


@pytest.mark.asyncio
async def test_delete_template(test_db, template_repo):
    """Delete template requires a user who owns the template."""
    from src.database.user_repo import UserRepository
    user_repo = UserRepository(test_db)

    user_id = await user_repo.create_user(telegram_id=55555, username="owner")
    tid = await template_repo.create_template(
        name="ToDelete", content="x", created_by=user_id
    )
    result = await template_repo.delete_template(telegram_id=55555, template_id=tid)
    assert result is True
    template = await template_repo.get_template(tid)
    assert template is None


@pytest.mark.asyncio
async def test_cannot_delete_default_template(test_db, template_repo):
    """System default templates cannot be deleted."""
    from src.database.user_repo import UserRepository
    user_repo = UserRepository(test_db)

    await user_repo.create_user(telegram_id=55555)
    tid = await template_repo.create_template(
        name="System", content="x", is_default=True
    )
    result = await template_repo.delete_template(telegram_id=55555, template_id=tid)
    assert result is False


# --- Обслуживание системных шаблонов (порт из монолита, #26) ---

async def test_system_template_exists_only_for_system_rows(test_db, template_repo, user_repo):
    user_id = await user_repo.create_user(telegram_id=42)
    await template_repo.create_template(name="Личный", content="c", created_by=user_id)
    await template_repo.create_template(name="Системный", content="c", created_by=None)

    assert await template_repo.system_template_exists("Системный") is True
    assert await template_repo.system_template_exists("Личный") is False
    assert await template_repo.system_template_exists("Несуществующий") is False


async def test_rename_system_template_touches_only_system_rows(test_db, template_repo, user_repo):
    user_id = await user_repo.create_user(telegram_id=43)
    user_tpl = await template_repo.create_template(name="Отчёт", content="c", created_by=user_id)
    await template_repo.create_template(name="Отчёт", content="c", created_by=None)

    renamed = await template_repo.rename_system_template("Отчёт", "Протокол встречи")

    assert renamed == 1
    assert (await template_repo.get_template(user_tpl))["name"] == "Отчёт"
    assert await template_repo.system_template_exists("Протокол встречи") is True


async def test_delete_system_template_by_name_keeps_user_rows(test_db, template_repo, user_repo):
    user_id = await user_repo.create_user(telegram_id=44)
    user_tpl = await template_repo.create_template(name="Дубль", content="c", created_by=user_id)
    await template_repo.create_template(name="Дубль", content="c", created_by=None)
    await template_repo.create_template(name="Дубль", content="c", created_by=None)

    deleted = await template_repo.delete_system_template_by_name("Дубль")

    assert deleted == 2
    assert (await template_repo.get_template(user_tpl)) is not None
