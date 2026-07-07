"""Тесты идемпотентной миграции шаблонов."""
import pytest

from src.services.template_maintenance import (
    REMOVE_NAMES,
    apply_template_maintenance,
)


async def _seed(db):
    # три англоязычных системных
    await db.create_template(name="Backlog Refinement", content="b", created_by=None, is_default=True)
    await db.create_template(name="Daily Standup", content="d", created_by=None, is_default=True)
    await db.create_template(name="Sprint Retrospective", content="s", created_by=None, is_default=True)
    # четыре системных сироты
    for n in REMOVE_NAMES:
        await db.create_template(name=n, content="o", created_by=None, is_default=True)
    # пользовательский шаблон, который НЕ трогаем
    await db.create_template(name="Простой шаблон", content="u", created_by=1, is_default=False)
    # пользовательский с именем из REMOVE_NAMES — тоже не трогаем
    await db.create_template(name="Мастер-класс", content="uu", created_by=1, is_default=False)


@pytest.mark.asyncio
async def test_maintenance_renames_and_deletes(template_repo):
    await _seed(template_repo)

    result = await apply_template_maintenance(template_repo)

    names = sorted(t["name"] for t in await template_repo.get_templates())
    # переименованы
    assert "Backlog Refinement" not in names
    assert "Груминг бэклога" in names
    assert "Дейли" in names
    assert "Ретроспектива спринта" in names
    # системные сироты удалены
    assert "Семинар и дискуссия" not in names
    assert "Стратегическая сессия руководства" not in names
    assert "Протокол с детализацией говорящих" not in names
    # пользовательские уцелели (включая одноимённый "Мастер-класс")
    rows = await template_repo.get_templates()
    user_rows = sorted(t["name"] for t in rows if t["created_by"] is not None)
    assert user_rows == ["Мастер-класс", "Простой шаблон"]
    assert result["renamed"] == 3
    assert result["deleted"] == 4
    assert result["deduped"] == 0


@pytest.mark.asyncio
async def test_maintenance_is_idempotent(template_repo):
    await _seed(template_repo)
    await apply_template_maintenance(template_repo)
    snapshot = sorted((t["name"], t["created_by"]) for t in await template_repo.get_templates())

    second = await apply_template_maintenance(template_repo)  # повторный прогон

    again = sorted((t["name"], t["created_by"]) for t in await template_repo.get_templates())
    assert again == snapshot          # состояние не изменилось
    assert second["renamed"] == 0     # нечего переименовывать
    assert second["deduped"] == 0
    assert second["deleted"] == 0


@pytest.mark.asyncio
async def test_maintenance_dedups_partial_run(template_repo):
    # уже есть и новое имя (системное), и старое — частичный прогон в прошлом
    await template_repo.create_template(name="Груминг бэклога", content="b", created_by=None, is_default=True)
    await template_repo.create_template(name="Backlog Refinement", content="b", created_by=None, is_default=True)

    result = await apply_template_maintenance(template_repo)

    names = [t["name"] for t in await template_repo.get_templates()]
    assert names.count("Груминг бэклога") == 1     # ровно один
    assert "Backlog Refinement" not in names        # устаревший убран
    assert result["deduped"] == 1
