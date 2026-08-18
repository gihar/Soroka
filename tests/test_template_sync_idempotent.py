"""Старт бота не переписывает шаблоны вхолостую.

Прод сообщал «Синхронизация стандартных шаблонов завершена: создано 0, обновлено
7» при КАЖДОМ запуске — семь раз из семи за две недели, включая перезапуски с
разницей в восемь минут и без единой правки шаблонов. Лог при этом не врал:
семь перезаписей действительно происходили.

Причиной был цикл между двумя компонентами. `_consolidate_templates` считала
себя применённой, если у шаблонов пустая категория, — и сама же категории
обнуляла. Категории системных шаблонов задаёт TemplateLibrary, поэтому
синхронизация возвращала их в БД, взводя сторож обратно. Каждый старт:
миграция чистит категории -> синхронизация видит расхождение во всех семи ->
переписывает их -> сторож снова взведён.

Отсюда два теста-контракта: одноразовая миграция применяется один раз (отметка,
а не догадка по данным), и повторный старт не делает ни одной записи.
"""

import aiosqlite
import pytest

from src.database.database import Database
from src.database.template_repo import TemplateRepository
from src.services.template_library import TemplateLibrary
from src.services.template_service import TemplateService

_MIGRATION = "consolidate_templates_27_to_7"


async def _start_bot_sequence(db: Database, service: TemplateService) -> None:
    """То, что делает bot.start: сначала init_db, потом синхронизация шаблонов."""
    await db.init_db()
    await service.init_default_templates()


@pytest.fixture
async def prepared(tmp_path):
    """Свежая БД, проведённая через один полный старт."""
    db_path = str(tmp_path / "bot.db")
    db = Database(db_path=db_path)
    service = TemplateService(templates=TemplateRepository(db))
    await _start_bot_sequence(db, service)
    return db_path, db, service


# ---------------------------------------------------------------------------
# 1. Повторный старт не пишет в шаблоны
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_start_updates_nothing(prepared, monkeypatch):
    db_path, db, service = prepared

    writes = []
    original = service._update_system_template

    async def spy(existing, template_data):
        writes.append(template_data["name"])
        await original(existing, template_data)

    monkeypatch.setattr(service, "_update_system_template", spy)
    await _start_bot_sequence(db, service)

    assert writes == [], f"второй старт переписал шаблоны: {writes}"


@pytest.mark.asyncio
async def test_categories_survive_a_restart(prepared):
    """Категорию задаёт TemplateLibrary — миграция не смеет её обнулять."""
    db_path, db, service = prepared
    await _start_bot_sequence(db, service)

    expected = {t["name"]: t["category"] for t in TemplateLibrary().get_all_templates()}
    stored = {t.name: t.category for t in await service.get_all_templates()}
    for name, category in expected.items():
        assert stored[name] == category, name


@pytest.mark.asyncio
async def test_template_timestamps_do_not_move_on_restart(prepared):
    """Наблюдаемое следствие: updated_at системных шаблонов стоит на месте."""
    db_path, db, service = prepared

    async def stamps():
        async with aiosqlite.connect(db_path) as conn:
            cursor = await conn.execute(
                "SELECT name, updated_at FROM templates ORDER BY name"
            )
            return await cursor.fetchall()

    before = await stamps()
    await _start_bot_sequence(db, service)
    assert await stamps() == before


# ---------------------------------------------------------------------------
# 2. Одноразовая миграция применяется один раз
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_is_recorded_once(prepared):
    db_path, db, service = prepared
    await _start_bot_sequence(db, service)

    async with aiosqlite.connect(db_path) as conn:
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM applied_migrations WHERE name = ?", (_MIGRATION,)
        )
        assert (await cursor.fetchone())[0] == 1


@pytest.mark.asyncio
async def test_marked_migration_does_not_delete_templates_again(prepared):
    """Миграция сносит шаблоны по жёстко зашитым id — второй раз она не запустится.

    Пока сторожем была категория, повторный запуск был реальным: DELETE по
    списку id и сброс пользовательских умолчаний повторялись при каждом старте.
    """
    db_path, db, service = prepared

    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO templates (id, name, content, description, is_default, "
            "created_by, category) VALUES (16, 'Чужой шаблон', '# Мой шаблон', '', 0, 1, 'general')"
        )
        await conn.commit()

    await _start_bot_sequence(db, service)

    async with aiosqlite.connect(db_path) as conn:
        cursor = await conn.execute("SELECT name FROM templates WHERE id = 16")
        assert await cursor.fetchone() is not None, "миграция снесла шаблон повторно"


@pytest.mark.asyncio
async def test_already_consolidated_database_is_only_marked(tmp_path):
    """Состояние прода: консолидация давно прошла, категории на месте, отметки нет.

    Первый старт с этой правкой обязан только поставить отметку — ничего не
    удалять, категории не трогать, шаблоны не переписывать.
    """
    db_path = str(tmp_path / "prod.db")
    db = Database(db_path=db_path)
    service = TemplateService(templates=TemplateRepository(db))
    await _start_bot_sequence(db, service)

    # Откатываем БД в дофиксовое состояние: отметки нет, категории проставлены.
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("DELETE FROM applied_migrations")
        await conn.commit()

    before = {t.name: (t.category, t.content) for t in await service.get_all_templates()}
    await _start_bot_sequence(db, service)

    assert {t.name: (t.category, t.content) for t in await service.get_all_templates()} == before

    async with aiosqlite.connect(db_path) as conn:
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM applied_migrations WHERE name = ?", (_MIGRATION,)
        )
        assert (await cursor.fetchone())[0] == 1


@pytest.mark.asyncio
async def test_migration_still_consolidates_an_unmigrated_database(tmp_path):
    """На непроведённой БД миграция обязана отработать — сторож не глушит её."""
    db_path = str(tmp_path / "old.db")
    db = Database(db_path=db_path)
    await db.init_db()

    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("DELETE FROM applied_migrations")
        await conn.execute(
            "INSERT INTO templates (id, name, content, description, is_default, "
            "created_by, category) VALUES (8, 'Старый шаблон', '# Старый шаблон', '', 1, NULL, 'sales')"
        )
        await conn.commit()

    await db.init_db()

    async with aiosqlite.connect(db_path) as conn:
        cursor = await conn.execute("SELECT COUNT(*) FROM templates WHERE id = 8")
        assert (await cursor.fetchone())[0] == 0, "консолидация не отработала"
