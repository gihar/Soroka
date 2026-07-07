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


# --- Шаблон по умолчанию: матрица прав (порт поведения монолита, #30) ---

async def test_set_default_template_unknown_user(user_repo):
    assert await user_repo.set_default_template(telegram_id=1, template_id=1) is False


async def test_set_default_template_smart_choice_skips_template_check(user_repo):
    await user_repo.create_user(telegram_id=50)

    # template_id=0 — «Умный выбор», проверка шаблона пропускается
    assert await user_repo.set_default_template(telegram_id=50, template_id=0) is True
    assert (await user_repo.get_user(50))["default_template_id"] == 0


async def test_set_default_template_nonexistent_template(user_repo):
    await user_repo.create_user(telegram_id=51)
    assert await user_repo.set_default_template(telegram_id=51, template_id=9999) is False


async def test_set_default_template_system_template_allowed(user_repo, template_repo):
    await user_repo.create_user(telegram_id=52)
    tpl = await template_repo.create_template(name="Системный", content="c", is_default=True)

    assert await user_repo.set_default_template(telegram_id=52, template_id=tpl) is True
    assert (await user_repo.get_user(52))["default_template_id"] == tpl


async def test_set_default_template_own_template_allowed(user_repo, template_repo):
    uid = await user_repo.create_user(telegram_id=53)
    tpl = await template_repo.create_template(name="Мой", content="c", created_by=uid)

    assert await user_repo.set_default_template(telegram_id=53, template_id=tpl) is True


async def test_set_default_template_foreign_template_denied(user_repo, template_repo):
    owner = await user_repo.create_user(telegram_id=54)
    await user_repo.create_user(telegram_id=55)
    tpl = await template_repo.create_template(name="Чужой", content="c", created_by=owner)

    assert await user_repo.set_default_template(telegram_id=55, template_id=tpl) is False


async def test_set_default_template_ownerless_template_allowed(user_repo, template_repo):
    await user_repo.create_user(telegram_id=56)
    tpl = await template_repo.create_template(name="Ничей", content="c", created_by=None)

    assert await user_repo.set_default_template(telegram_id=56, template_id=tpl) is True


async def test_set_default_template_legacy_owner_synced(user_repo, template_repo):
    """Legacy-записи: created_by = telegram_id → выравнивается на внутренний id."""
    uid = await user_repo.create_user(telegram_id=57)
    tpl = await template_repo.create_template(name="Легаси", content="c", created_by=57)

    assert await user_repo.set_default_template(telegram_id=57, template_id=tpl) is True
    assert (await template_repo.get_template(tpl))["created_by"] == uid


async def test_reset_default_template(user_repo, template_repo):
    uid = await user_repo.create_user(telegram_id=58)
    tpl = await template_repo.create_template(name="Т", content="c", created_by=uid)
    await user_repo.set_default_template(telegram_id=58, template_id=tpl)

    assert await user_repo.reset_default_template(telegram_id=58) is True
    assert (await user_repo.get_user(58))["default_template_id"] is None
    assert await user_repo.reset_default_template(telegram_id=404) is False


# --- Сохранённые участники (#30) ---

async def test_update_saved_participants_round_trip(user_repo):
    await user_repo.create_user(telegram_id=59)
    payload = '[{"name": "Анна", "role": "РП"}]'

    assert await user_repo.update_saved_participants(59, payload) is True
    assert (await user_repo.get_user(59))["saved_participants"] == payload


# --- Шаблоны: полная характеризация перед переключением (#31) ---

async def test_get_user_templates_unknown_user_is_empty(template_repo):
    assert await template_repo.get_user_templates(telegram_id=9001) == []


async def test_get_user_templates_returns_own_and_system(template_repo, user_repo):
    uid = await user_repo.create_user(telegram_id=60)
    stranger = await user_repo.create_user(telegram_id=61)
    await template_repo.create_template(name="Свой", content="c", created_by=uid)
    await template_repo.create_template(name="Системный", content="c", is_default=True)
    await template_repo.create_template(name="Чужой", content="c", created_by=stranger)

    names = [t["name"] for t in await template_repo.get_user_templates(60)]

    assert names == ["Системный", "Свой"]  # системные впереди, далее по имени


async def test_template_json_fields_round_trip(template_repo):
    tpl = await template_repo.create_template(
        name="Теги", content="c",
        tags=["встреча", "статус"], keywords=["протокол"],
    )

    loaded = await template_repo.get_template(tpl)

    assert loaded["tags"] == ["встреча", "статус"]
    assert loaded["keywords"] == ["протокол"]


async def test_update_template_rewrites_all_fields(template_repo):
    tpl = await template_repo.create_template(name="До", content="старое")

    ok = await template_repo.update_template(
        tpl, name="После", content="новое", description="описание",
        tags=["a"], keywords=["b"],
    )

    assert ok is True
    loaded = await template_repo.get_template(tpl)
    assert loaded["name"] == "После"
    assert loaded["content"] == "новое"
    assert loaded["description"] == "описание"
    assert loaded["tags"] == ["a"]
    assert loaded["keywords"] == ["b"]


async def test_update_nonexistent_template_returns_false(template_repo):
    assert await template_repo.update_template(4242, name="x", content="y") is False


async def test_delete_template_denied_for_foreign_and_unknown(template_repo, user_repo):
    owner = await user_repo.create_user(telegram_id=62)
    await user_repo.create_user(telegram_id=63)
    tpl = await template_repo.create_template(name="Чужой", content="c", created_by=owner)

    assert await template_repo.delete_template(telegram_id=63, template_id=tpl) is False
    assert await template_repo.delete_template(telegram_id=9002, template_id=tpl) is False
    assert await template_repo.delete_template(telegram_id=62, template_id=9999) is False


async def test_delete_template_allows_legacy_telegram_owner(template_repo, user_repo):
    await user_repo.create_user(telegram_id=64)
    tpl = await template_repo.create_template(name="Легаси", content="c", created_by=64)

    assert await template_repo.delete_template(telegram_id=64, template_id=tpl) is True


async def test_delete_template_resets_user_defaults(template_repo, user_repo):
    uid = await user_repo.create_user(telegram_id=65)
    tpl = await template_repo.create_template(name="Дефолтный", content="c", created_by=uid)
    await user_repo.set_default_template(telegram_id=65, template_id=tpl)

    assert await template_repo.delete_template(telegram_id=65, template_id=tpl) is True
    assert (await user_repo.get_user(65))["default_template_id"] is None
