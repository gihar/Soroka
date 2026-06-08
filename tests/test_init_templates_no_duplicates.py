"""init_default_templates после миграции не плодит дубли."""
import pytest

from src.services.template_service import TemplateService


@pytest.mark.asyncio
async def test_init_renames_without_duplicates(test_db):
    # старое состояние БД: англоязычный системный + системная сирота
    await test_db.create_template(name="Daily Standup", content="old content placeholder", created_by=None, is_default=True)
    await test_db.create_template(name="Мастер-класс", content="orphan content placeholder", created_by=None, is_default=True)

    service = TemplateService()
    service.db = test_db  # направляем на временную БД вместо глобальной

    await service.init_default_templates()

    names = [t.name for t in await service.get_all_templates()]
    assert names.count("Дейли") == 1         # ровно один, без дубля
    assert "Daily Standup" not in names       # старое имя ушло
    assert "Мастер-класс" not in names         # сирота удалена
