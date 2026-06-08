# Переименование шаблонов на русский + алфавитная сортировка — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Переименовать три англоязычных системных шаблона на русский, удалить четыре системных шаблона-сироты из прод-БД, и выводить список шаблонов в UI по алфавиту — без задвоений и без удаления пользовательских шаблонов.

**Architecture:** Идемпотентная миграция в коде (`template_maintenance.py`) запускается на старте бота внутри `init_default_templates()` до синхронизации код→БД; работает только над системными строками (`created_by IS NULL`). UI-сортировка по алфавиту вынесена в общий хелпер и применена в 5 местах; DB-сортировка не меняется.

**Tech Stack:** Python 3.11, aiosqlite, aiogram, pytest (`asyncio_mode=auto`), Jinja2.

**Spec:** `docs/superpowers/specs/2026-06-08-rename-templates-russian-design.md`

---

## Контекст для исполнителя (прочитать до старта)

- Живой объект БД — это класс `Database` в `src/database/database.py` (инлайн-SQL). Глобальный
  синглтон импортируется как `from database import db`. **Новые методы БД добавляем именно в этот
  класс** (не в `src/database/template_repo.py` — он не подключён к живому `db`). Это уточнение к
  спеке, где упоминался `template_repo.py`.
- Тестовая фикстура `test_db` (в `tests/conftest.py`) даёт временную файловую SQLite с уже
  созданной схемой (`await db.init_db()`). Используем её.
- `asyncio_mode = "auto"` (pyproject.toml) — тестовые корутины используем с `@pytest.mark.asyncio`
  для единообразия с `tests/test_app_settings_repo.py`.
- Колонка `templates.name` — `TEXT NOT NULL`, **без UNIQUE**. `created_by INTEGER` (NULL = системный
  шаблон). FK не форсится (PRAGMA foreign_keys по умолчанию off) — в тестах можно ставить
  `created_by=1` без строки в `users`.
- Синхронизация `init_default_templates` матчит шаблоны **по `name`**: новое имя в коде без
  переименования строки в БД создаст дубль.

## Карта файлов

**Создать:**
- `src/services/template_maintenance.py` — `RENAME_MAP`, `REMOVE_NAMES`, `apply_template_maintenance(db)`.
- `src/utils/template_sort.py` — `sort_templates_by_name(templates)`.
- `tests/test_template_db_system_methods.py` — тесты низкоуровневых методов БД.
- `tests/test_template_maintenance.py` — юнит-тесты миграции (идемпотентность, защита user-строк).
- `tests/test_template_library_names.py` — тест, что в коде нет англоязычных имён.
- `tests/test_init_templates_no_duplicates.py` — интеграционный тест на отсутствие дублей.
- `tests/test_template_sort.py` — тест сортировки.

**Изменить:**
- `src/database/database.py` — добавить 3 метода: `system_template_exists`, `rename_system_template`,
  `delete_system_template_by_name`.
- `src/services/template_service.py` — вызвать `apply_template_maintenance` в `init_default_templates`.
- `src/services/template_library.py` — русифицировать имена и H1-заголовки двух шаблонов.
- `src/ux/quick_actions.py` — заменить ключ сортировки (1 место).
- `src/handlers/callbacks/template_callbacks.py` — заменить ключ сортировки (3 места) + импорт.
- `src/handlers/callbacks/template_mgmt_callbacks.py` — заменить ключ сортировки (1 место) + импорт.

---

## Task 1: Низкоуровневые методы БД для системных шаблонов

**Files:**
- Modify: `src/database/database.py` (добавить методы рядом с `create_template`, после строки ~403)
- Test: `tests/test_template_db_system_methods.py`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_template_db_system_methods.py`:

```python
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
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `python -m pytest tests/test_template_db_system_methods.py -v`
Expected: FAIL — `AttributeError: 'Database' object has no attribute 'rename_system_template'`.

- [ ] **Step 3: Реализовать методы**

В `src/database/database.py` сразу после метода `create_template` (после строки ~403) добавить:

```python
    async def system_template_exists(self, name: str) -> bool:
        """Есть ли системный шаблон (created_by IS NULL) с таким именем."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT 1 FROM templates WHERE name = ? AND created_by IS NULL LIMIT 1",
                (name,),
            )
            return await cursor.fetchone() is not None

    async def rename_system_template(self, old_name: str, new_name: str) -> int:
        """Переименовать системные шаблоны old_name -> new_name. Возвращает число строк."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "UPDATE templates SET name = ? WHERE name = ? AND created_by IS NULL",
                (new_name, old_name),
            )
            await db.commit()
            return cursor.rowcount

    async def delete_system_template_by_name(self, name: str) -> int:
        """Удалить системные шаблоны с именем name. Возвращает число удалённых строк."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM templates WHERE name = ? AND created_by IS NULL",
                (name,),
            )
            await db.commit()
            return cursor.rowcount
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `python -m pytest tests/test_template_db_system_methods.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/database/database.py tests/test_template_db_system_methods.py
git commit -m "feat(db): add system-template rename/delete/exists helpers"
```

---

## Task 2: Модуль миграции `template_maintenance`

**Files:**
- Create: `src/services/template_maintenance.py`
- Test: `tests/test_template_maintenance.py`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_template_maintenance.py`:

```python
"""Тесты идемпотентной миграции шаблонов."""
import pytest

from src.services.template_maintenance import (
    REMOVE_NAMES,
    RENAME_MAP,
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
async def test_maintenance_renames_and_deletes(test_db):
    await _seed(test_db)

    result = await apply_template_maintenance(test_db)

    names = sorted(t["name"] for t in await test_db.get_templates())
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
    rows = await test_db.get_templates()
    user_rows = sorted(t["name"] for t in rows if t["created_by"] is not None)
    assert user_rows == ["Мастер-класс", "Простой шаблон"]
    assert result["renamed"] == 3


@pytest.mark.asyncio
async def test_maintenance_is_idempotent(test_db):
    await _seed(test_db)
    await apply_template_maintenance(test_db)
    snapshot = sorted((t["name"], t["created_by"]) for t in await test_db.get_templates())

    second = await apply_template_maintenance(test_db)  # повторный прогон

    again = sorted((t["name"], t["created_by"]) for t in await test_db.get_templates())
    assert again == snapshot          # состояние не изменилось
    assert second["renamed"] == 0     # нечего переименовывать


@pytest.mark.asyncio
async def test_maintenance_dedups_partial_run(test_db):
    # уже есть и новое имя (системное), и старое — частичный прогон в прошлом
    await test_db.create_template(name="Груминг бэклога", content="b", created_by=None, is_default=True)
    await test_db.create_template(name="Backlog Refinement", content="b", created_by=None, is_default=True)

    result = await apply_template_maintenance(test_db)

    names = [t["name"] for t in await test_db.get_templates()]
    assert names.count("Груминг бэклога") == 1     # ровно один
    assert "Backlog Refinement" not in names        # устаревший убран
    assert result["deduped"] >= 1
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `python -m pytest tests/test_template_maintenance.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.services.template_maintenance'`.

- [ ] **Step 3: Реализовать модуль**

Создать `src/services/template_maintenance.py`:

```python
"""Идемпотентная миграция системных шаблонов: переименование и удаление сирот.

Запускается на старте бота из TemplateService.init_default_templates() ДО
синхронизации код→БД. Работает только над системными строками (created_by IS NULL),
поэтому пользовательские шаблоны никогда не затрагиваются. Безопасна к повторному запуску.
"""
from loguru import logger

# old (как лежит в БД) -> new (русское имя)
RENAME_MAP = {
    "Daily Standup": "Дейли",
    "Sprint Retrospective": "Ретроспектива спринта",
    "Backlog Refinement": "Груминг бэклога",
}

# системные шаблоны-сироты (нет в коде) на удаление
REMOVE_NAMES = [
    "Мастер-класс",
    "Семинар и дискуссия",
    "Стратегическая сессия руководства",
    "Протокол с детализацией говорящих",
]


async def apply_template_maintenance(db) -> dict:
    """Переименовать англоязычные системные шаблоны и удалить системных сирот.

    Returns:
        dict со счётчиками {renamed, deduped, deleted}.
    """
    renamed = 0
    deduped = 0
    deleted = 0

    for old_name, new_name in RENAME_MAP.items():
        if await db.system_template_exists(new_name):
            # целевое имя уже есть (повторный/частичный прогон) — убрать устаревший дубль
            deduped += await db.delete_system_template_by_name(old_name)
        else:
            renamed += await db.rename_system_template(old_name, new_name)

    for name in REMOVE_NAMES:
        deleted += await db.delete_system_template_by_name(name)

    result = {"renamed": renamed, "deduped": deduped, "deleted": deleted}
    logger.info("Обслуживание шаблонов завершено: %s", result)
    return result
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `python -m pytest tests/test_template_maintenance.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/services/template_maintenance.py tests/test_template_maintenance.py
git commit -m "feat(templates): idempotent maintenance migration (rename + delete orphans)"
```

---

## Task 3: Русифицировать имена и заголовки в `template_library.py`

**Files:**
- Modify: `src/services/template_library.py` (Daily Standup ~строки 42-70, Sprint Retrospective ~строки 72-107)
- Test: `tests/test_template_library_names.py`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_template_library_names.py`:

```python
"""Шаблоны в коде должны иметь русские имена."""
from src.services.template_library import TemplateLibrary


def test_no_english_template_names():
    names = {t["name"] for t in TemplateLibrary().get_all_templates()}
    assert "Daily Standup" not in names
    assert "Sprint Retrospective" not in names
    assert "Дейли" in names
    assert "Ретроспектива спринта" in names


def test_template_content_headers_russified():
    by_name = {t["name"]: t["content"] for t in TemplateLibrary().get_all_templates()}
    assert "# Daily Standup" not in by_name["Дейли"]
    assert by_name["Дейли"].lstrip().startswith("# Дейли")
    assert "# Sprint Retrospective" not in by_name["Ретроспектива спринта"]
    assert "# Ретроспектива спринта" in by_name["Ретроспектива спринта"]
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `python -m pytest tests/test_template_library_names.py -v`
Expected: FAIL — `assert 'Дейли' in names` (имена ещё английские).

- [ ] **Step 3: Внести правки в `src/services/template_library.py`**

Правка A — имя Daily Standup (строка 42):

```python
                "name": "Дейли",
```

Правка B — H1-заголовок в content Daily Standup (строка 47, первая строка `content="""# Daily Standup`):
заменить `# Daily Standup` на `# Дейли`.

Правка C — имя Sprint Retrospective (строка 73):

```python
                "name": "Ретроспектива спринта",
```

Правка D — H1-заголовок в content Sprint Retrospective (строка 78, первая строка `content="""# Sprint Retrospective`):
заменить `# Sprint Retrospective` на `# Ретроспектива спринта`.
(строку-футер `*Retro generated automatically*` оставить как есть)

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `python -m pytest tests/test_template_library_names.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/services/template_library.py tests/test_template_library_names.py
git commit -m "feat(templates): russify Daily Standup and Sprint Retrospective names/headers"
```

---

## Task 4: Подключить миграцию к старту и проверить отсутствие дублей

**Files:**
- Modify: `src/services/template_service.py` (метод `init_default_templates`, строки ~160-161)
- Test: `tests/test_init_templates_no_duplicates.py`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_init_templates_no_duplicates.py`:

```python
"""init_default_templates после миграции не плодит дубли."""
import pytest

from src.services.template_service import TemplateService


@pytest.mark.asyncio
async def test_init_renames_without_duplicates(test_db):
    # старое состояние БД: англоязычный системный + системная сирота
    await test_db.create_template(name="Daily Standup", content="old", created_by=None, is_default=True)
    await test_db.create_template(name="Мастер-класс", content="orphan", created_by=None, is_default=True)

    service = TemplateService()
    service.db = test_db  # направляем на временную БД вместо глобальной

    await service.init_default_templates()

    names = [t.name for t in await service.get_all_templates()]
    assert names.count("Дейли") == 1         # ровно один, без дубля
    assert "Daily Standup" not in names       # старое имя ушло
    assert "Мастер-класс" not in names         # сирота удалена
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `python -m pytest tests/test_init_templates_no_duplicates.py -v`
Expected: FAIL — в `names` есть и `"Daily Standup"`, и `"Дейли"` (дубль), потому что миграция ещё не вызвана.

- [ ] **Step 3: Вызвать миграцию в `init_default_templates`**

В `src/services/template_service.py`, в начале `init_default_templates` (сейчас строки 160-162):

```python
            # Гарантируем, что схема таблицы templates поддерживает auto-update
            await self.db.ensure_templates_updated_at_column()
            existing_templates = await self.get_all_templates()
```

заменить на:

```python
            # Гарантируем, что схема таблицы templates поддерживает auto-update
            await self.db.ensure_templates_updated_at_column()
            # Переименование англоязычных шаблонов и удаление системных сирот (идемпотентно)
            from src.services.template_maintenance import apply_template_maintenance
            await apply_template_maintenance(self.db)
            existing_templates = await self.get_all_templates()
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `python -m pytest tests/test_init_templates_no_duplicates.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add src/services/template_service.py tests/test_init_templates_no_duplicates.py
git commit -m "feat(templates): run maintenance migration before default-template sync"
```

---

## Task 5: Хелпер алфавитной сортировки

**Files:**
- Create: `src/utils/template_sort.py`
- Test: `tests/test_template_sort.py`

> Примечание: спека упоминала `src/ux/template_sort.py`, но хелпер используют и хендлеры, и UX —
> кладём в нейтральный `src/utils/` (там уже живут общие утилиты), чтобы хендлеры не зависели от слоя ux.

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_template_sort.py`:

```python
"""Тест алфавитной сортировки шаблонов."""
from dataclasses import dataclass

from src.utils.template_sort import sort_templates_by_name


@dataclass
class _T:
    name: str
    is_default: bool = False


def test_sorts_alphabetically_ignoring_is_default():
    items = [
        _T("Техническое совещание", True),
        _T("Груминг бэклога", True),
        _T("Простой шаблон", False),  # не-дефолтный не должен «тонуть» вниз
        _T("Дейли", True),
    ]
    result = [t.name for t in sort_templates_by_name(items)]
    assert result == ["Груминг бэклога", "Дейли", "Простой шаблон", "Техническое совещание"]


def test_casefold_mixed_case():
    items = [_T("яблоко"), _T("Яблоко"), _T("Арбуз")]
    result = [t.name for t in sort_templates_by_name(items)]
    assert result[0] == "Арбуз"  # «А» < «я» по алфавиту, регистр не мешает


def test_returns_new_list_without_mutating_input():
    items = [_T("Б"), _T("А")]
    out = sort_templates_by_name(items)
    assert [t.name for t in items] == ["Б", "А"]  # вход не изменён
    assert [t.name for t in out] == ["А", "Б"]
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `python -m pytest tests/test_template_sort.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.utils.template_sort'`.

- [ ] **Step 3: Реализовать хелпер**

Создать `src/utils/template_sort.py`:

```python
"""Алфавитная сортировка шаблонов для отображения в UI."""
from typing import List


def sort_templates_by_name(templates: List) -> List:
    """Вернуть новый список шаблонов, отсортированный по имени (регистронезависимо).

    Не мутирует вход. Сортировка строго по алфавиту, без приоритета is_default.
    """
    return sorted(templates, key=lambda t: t.name.casefold())
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `python -m pytest tests/test_template_sort.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/utils/template_sort.py tests/test_template_sort.py
git commit -m "feat(ux): add alphabetical template sort helper"
```

---

## Task 6: Применить алфавитную сортировку во всех UI-местах

**Files:**
- Modify: `src/ux/quick_actions.py:350`
- Modify: `src/handlers/callbacks/template_callbacks.py:25, 66, 268` (+ импорт)
- Modify: `src/handlers/callbacks/template_mgmt_callbacks.py:27` (+ импорт)

Во всех местах заменяем in-place сортировку с приоритетом `is_default` на вызов хелпера.

- [ ] **Step 1: `src/ux/quick_actions.py`**

Добавить импорт рядом с прочими импортами вверху файла:

```python
from src.utils.template_sort import sort_templates_by_name
```

Строку 350 заменить:

```python
            templates.sort(key=lambda t: (not t.is_default, t.name))
```

на:

```python
            templates = sort_templates_by_name(templates)
```

- [ ] **Step 2: `src/handlers/callbacks/template_callbacks.py`**

Добавить импорт вверху файла:

```python
from src.utils.template_sort import sort_templates_by_name
```

Заменить КАЖДУЮ из трёх строк (около строк 25, 66, 268):

```python
    templates.sort(key=lambda t: (not t.is_default, t.name))
```

на (сохранив исходный отступ строки):

```python
    templates = sort_templates_by_name(templates)
```

- [ ] **Step 3: `src/handlers/callbacks/template_mgmt_callbacks.py`**

Добавить импорт вверху файла:

```python
from src.utils.template_sort import sort_templates_by_name
```

Строку 27 заменить:

```python
            templates.sort(key=lambda t: (not t.is_default, t.name))
```

на:

```python
            templates = sort_templates_by_name(templates)
```

- [ ] **Step 4: Проверить, что не осталось старого ключа сортировки**

Run: `grep -rn "not t.is_default, t.name" src/`
Expected: пусто (ни одного совпадения).

- [ ] **Step 5: Импорт-санити затронутых модулей**

Run: `python -c "import src.ux.quick_actions, src.handlers.callbacks.template_callbacks, src.handlers.callbacks.template_mgmt_callbacks; print('imports ok')"`
Expected: `imports ok` (нет ошибок импорта).

- [ ] **Step 6: Commit**

```bash
git add src/ux/quick_actions.py src/handlers/callbacks/template_callbacks.py src/handlers/callbacks/template_mgmt_callbacks.py
git commit -m "feat(ux): sort template lists alphabetically in all menus"
```

---

## Task 7: Полный прогон тестов и финальная проверка

**Files:** (нет правок кода; проверка)

- [ ] **Step 1: Прогнать весь набор тестов**

Run: `python -m pytest tests/ -q`
Expected: все тесты зелёные (включая новые файлы). Если что-то падает — чинить реализацию, не тесты
(кроме случая, когда тест явно неверен).

- [ ] **Step 2: Проверить, что в коде не осталось англоязычных имён шаблонов**

Run: `grep -rn '"Daily Standup"\|"Sprint Retrospective"\|"Backlog Refinement"' src/`
Expected: пусто (ни одного совпадения).

- [ ] **Step 3: Финальный коммит (если остались несохранённые изменения)**

```bash
git status
# при необходимости:
git add -A && git commit -m "chore(templates): finalize russification + alphabetical sort"
```

---

## Деплой (после мерджа, выполняется пользователем вручную)

На проде (`ssh jimmy@37.46.16.109`, каталог `/home/jimmy/Soroka`):

```bash
git pull
sudo systemctl restart soroka.service
```

Миграция `apply_template_maintenance` применится автоматически при старте: переименует строки
17/15/29, удалит сирот 23/22/6/4, не тронет пользовательский «Простой шаблон». Проверка результата
(read-only):

```bash
python3 - <<'PY'
import sqlite3
c = sqlite3.connect("/home/jimmy/Soroka/bot.db")
for r in c.execute("SELECT name, is_default, created_by FROM templates ORDER BY name").fetchall():
    print(r)
PY
```
Expected: 9 строк, все имена русские, в порядке по алфавиту, «Простой шаблон» на месте.

---

## Самопроверка плана (выполнена автором)

- **Покрытие спеки:** переименование 3 имён (Task 2 миграция + Task 3 код); удаление 4 сирот
  (Task 2); защита пользовательских шаблонов через `created_by IS NULL` (Task 1/2, тесты); вызов
  миграции до синхронизации (Task 4); идемпотентность (Task 2 тест); алфавитная сортировка только в
  UI (Task 5/6); DB ORDER BY не трогается (нигде не меняется); тесты
  миграции/сортировки/дублей/имён — все присутствуют.
- **Плейсхолдеры:** нет TBD/TODO; во всех шагах приведён конкретный код и команды.
- **Согласованность имён:** методы БД `system_template_exists` / `rename_system_template` /
  `delete_system_template_by_name` используются с теми же сигнатурами в `apply_template_maintenance`;
  хелпер `sort_templates_by_name` вызывается одинаково во всех 5 местах; `RENAME_MAP`/`REMOVE_NAMES`
  согласованы между Task 2 и тестами Task 3/4.
