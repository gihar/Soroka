"""Тесты низкоуровневых методов БД для системных шаблонов."""
import pytest


@pytest.mark.asyncio
async def test_rename_only_touches_system_rows(test_db):
    # системный шаблон (created_by IS NULL)
    await test_db.create_template(name="Daily Standup", content="x", created_by=None, is_default=True)
    # одноимённый пользовательский шаблон (created_by != NULL) — не должен затрагиваться
    await test_db.create_template(name="Daily Standup", content="y", created_by=1, is_default=False)

    affected = await test_db.rename_system_template("Daily Standup", "Дейли")

    assert affected == 1
    names = sorted(t["name"] for t in await test_db.get_templates())
    assert names == ["Daily Standup", "Дейли"]  # user-строка осталась как была


@pytest.mark.asyncio
async def test_delete_only_touches_system_rows(test_db):
    await test_db.create_template(name="Мастер-класс", content="x", created_by=None, is_default=True)
    await test_db.create_template(name="Мастер-класс", content="y", created_by=1, is_default=False)

    deleted = await test_db.delete_system_template_by_name("Мастер-класс")

    assert deleted == 1
    rows = await test_db.get_templates()
    assert len(rows) == 1
    assert rows[0]["created_by"] == 1  # уцелел пользовательский


@pytest.mark.asyncio
async def test_system_template_exists(test_db):
    await test_db.create_template(name="Дейли", content="x", created_by=None, is_default=True)
    assert await test_db.system_template_exists("Дейли") is True
    assert await test_db.system_template_exists("Нет такого") is False
    # пользовательский с тем же именем не считается системным
    await test_db.create_template(name="UserOnly", content="y", created_by=1, is_default=False)
    assert await test_db.system_template_exists("UserOnly") is False
