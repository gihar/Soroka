# Template Consolidation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce 27 templates to 7, remove categories, flatten all template selection UIs to a simple list.

**Architecture:** Database migration to delete unused templates + code changes to remove category grouping logic from UI handlers. template_library.py rewritten with 7 flat templates. All category-based callbacks simplified to show flat template lists.

**Tech Stack:** Python 3.11, SQLite, Aiogram 3.x, Jinja2

---

## Task 1: Database Migration — Delete Templates & Reset Defaults

**Files:**
- Modify: `src/database/database.py` (add migration method)

**Step 1: Write the migration method**

Add to the `Database` class `init_db()` method, after existing migrations (around line 220):

```python
# Migration: consolidate templates (27 -> 7)
await self._consolidate_templates(db)
```

Add new method to Database class:

```python
async def _consolidate_templates(self, db):
    """One-time migration: reduce templates from 27 to 7, remove categories."""
    # Check if migration already ran (marker: no templates with category set)
    cursor = await db.execute(
        "SELECT COUNT(*) FROM templates WHERE category IS NOT NULL AND category != ''"
    )
    row = await cursor.fetchone()
    if row[0] == 0:
        return  # Already migrated

    logger.info("Running template consolidation migration (27 -> 7)...")

    # Merge OD template duplicates: redirect history from 31 to 22
    await db.execute("UPDATE processing_history SET template_id = 22 WHERE template_id = 31")

    # Reset user defaults pointing to templates being deleted
    deleted_ids = (7, 8, 9, 10, 11, 12, 13, 14, 16, 18, 19, 20, 21, 24, 25, 26, 27, 28, 29, 31)
    placeholders = ",".join("?" * len(deleted_ids))
    await db.execute(
        f"UPDATE users SET default_template_id = NULL WHERE default_template_id IN ({placeholders})",
        deleted_ids
    )

    # Delete templates
    await db.execute(f"DELETE FROM templates WHERE id IN ({placeholders})", deleted_ids)

    # Clear category on remaining templates
    await db.execute("UPDATE templates SET category = NULL")

    await db.commit()
    logger.info("Template consolidation migration complete. Remaining templates: 7")
```

**Step 2: Verify migration works**

```bash
source venv/bin/activate
python -c "
import asyncio
from database import db
async def test():
    await db.init_db()
    import aiosqlite
    async with aiosqlite.connect('bot.db') as conn:
        cursor = await conn.execute('SELECT COUNT(*) FROM templates')
        row = await cursor.fetchone()
        print(f'Templates remaining: {row[0]}')
        cursor = await conn.execute('SELECT id, name FROM templates ORDER BY id')
        for row in await cursor.fetchall():
            print(f'  {row[0]}: {row[1]}')
asyncio.run(test())
"
```

Expected: 7 templates remaining (IDs 1, 2, 3, 15, 17, 22, 23).

**Step 3: Commit**

```bash
git add src/database/database.py
git commit -m "feat: add template consolidation migration (27 -> 7 templates)"
```

---

## Task 2: Rewrite template_library.py — Flat List of 7 Templates

**Files:**
- Modify: `src/services/template_library.py`

**Step 1: Replace entire file**

Replace the entire content of `src/services/template_library.py` with a flat list. Remove `CATEGORIES` dict, remove per-category methods. Keep only `get_all_templates()` returning 7 template dicts.

The 7 templates to keep (copy content verbatim from current file/DB):
1. "Стандартный протокол встречи" — from `template_service.py:_get_default_templates()` (line 211)
2. "Краткое резюме встречи" — from `template_service.py:_get_default_templates()`
3. "Техническое совещание" — from `template_service.py:_get_default_templates()`
4. "Daily Standup" — from current `get_product_templates()[3]` (line 387)
5. "Протокол поручений" — from current `get_management_templates()[0]` (line 22, the od_protocol)
6. "Sprint Retrospective" — from current `get_product_templates()[1]` (line 312)
7. "Лекция и презентация" — from current `get_educational_templates()[0]` (line 497)

Remove `category` field from all template dicts (or set to `None`).

New structure:

```python
"""
Библиотека шаблонов для встреч — 7 core templates.
"""

from typing import List, Dict, Any


class TemplateLibrary:
    """Библиотека шаблонов"""

    def get_all_templates(self) -> List[Dict[str, Any]]:
        """Return all built-in templates as flat list."""
        return [
            # 1. Протокол поручений (OD)
            {
                "id": "od_protocol",
                "name": "Протокол поручений руководителей",
                ...  # content from current get_management_templates()[0]
            },
            # 2. Daily Standup
            {
                "name": "Daily Standup",
                ...  # content from current get_product_templates()[3]
            },
            # 3. Sprint Retrospective
            {
                "name": "Sprint Retrospective",
                ...  # content from current get_product_templates()[1]
            },
            # 4. Лекция и презентация
            {
                "id": "education_lecture",
                "name": "Лекция и презентация",
                ...  # content from current get_educational_templates()[0]
            },
        ]
```

Note: "Стандартный протокол", "Краткое резюме", "Техническое совещание" are defined in `template_service.py:_get_default_templates()` — they stay there. `template_library.py` only needs the other 4 that aren't in `_get_default_templates()`.

**Step 2: Check what _get_default_templates returns**

Read `template_service.py:209-350` to see which 3 templates are already defined there. The library only needs the remaining 4.

**Step 3: Verify**

```bash
python -c "
from src.services.template_library import TemplateLibrary
lib = TemplateLibrary()
templates = lib.get_all_templates()
print(f'Library templates: {len(templates)}')
for t in templates:
    print(f'  - {t[\"name\"]}')
"
```

**Step 4: Commit**

```bash
git add src/services/template_library.py
git commit -m "refactor: reduce template_library.py from 27 to 4 templates (7 total with defaults)"
```

---

## Task 3: Flatten template_callbacks.py — Remove Category Navigation

**Files:**
- Modify: `src/handlers/callbacks/template_callbacks.py`

This is the biggest change. Three places show category-based navigation that need to become flat lists:

### Step 1: Flatten `select_template_once_callback` (lines 22-98)

Replace the category grouping logic with a flat template list:

```python
@router.callback_query(F.data == "select_template_once")
async def select_template_once_callback(callback: CallbackQuery, state: FSMContext):
    """Разовый выбор шаблона — плоский список"""
    try:
        await _safe_callback_answer(callback)
        templates = await template_service.get_all_templates()

        if not templates:
            await safe_edit_text(callback.message,
                "❌ **Шаблоны не найдены**",
                parse_mode="Markdown"
            )
            return

        templates.sort(key=lambda t: (not t.is_default, t.name))

        keyboard_buttons = [
            [InlineKeyboardButton(
                text=t.name,
                callback_data=f"select_template_id_{t.id}"
            )] for t in templates
        ]

        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

        await safe_edit_text(callback.message,
            "📋 **Выберите шаблон:**\n\n"
            "Шаблон будет использован для текущей обработки.",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

    except Exception as e:
        logger.error(f"Ошибка в select_template_once_callback: {e}")
        await _safe_callback_answer(callback, "❌ Произошла ошибка")
```

### Step 2: Remove `select_category_callback` (lines 100-154)

Delete entire handler — no longer needed.

### Step 3: Flatten `back_to_template_categories_callback` (lines 371-428)

Rename to `back_to_template_selection_callback`. Replace category logic with flat list + smart selection button:

```python
@router.callback_query(F.data == "back_to_template_categories")
async def back_to_template_selection_callback(callback: CallbackQuery, state: FSMContext):
    """Возврат к выбору шаблонов — плоский список"""
    try:
        templates = await template_service.get_all_templates()
        templates.sort(key=lambda t: (not t.is_default, t.name))

        keyboard_buttons = [
            [InlineKeyboardButton(
                text="🤖 Умный выбор шаблона",
                callback_data="smart_template_selection"
            )]
        ]

        keyboard_buttons.extend([
            [InlineKeyboardButton(
                text=t.name,
                callback_data=f"select_template_{t.id}"
            )] for t in templates
        ])

        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

        await safe_edit_text(callback.message,
            "📝 **Выберите шаблон для протокола:**\n\n"
            "🤖 **Умный выбор** — ИИ подберёт шаблон автоматически",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await callback.answer("❌ Произошла ошибка")
```

### Step 4: Flatten `template_category_callback` (lines 260-315)

Replace with flat list for "set default" flow. Instead of showing categories first, show templates directly:

```python
@router.callback_query(F.data.startswith("template_category_"))
async def template_category_callback(callback: CallbackQuery):
    """Backward-compat: redirect to flat template list for default selection"""
    # Redirect to settings_default_template which will show flat list
    templates = await template_service.get_all_templates()
    templates.sort(key=lambda t: (not t.is_default, t.name))

    keyboard_buttons = [
        [InlineKeyboardButton(
            text=t.name,
            callback_data=f"set_default_template_{t.id}"
        )] for t in templates
    ]
    keyboard_buttons.append([InlineKeyboardButton(
        text="⬅️ Назад",
        callback_data="settings_default_template"
    )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    await safe_edit_text(callback.message,
        "📝 **Выберите шаблон по умолчанию:**",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()
```

### Step 5: Flatten `file_template_category_callback` (lines 317-369)

Same pattern — replace category filtering with flat list:

```python
@router.callback_query(F.data.startswith("file_template_category_"))
async def file_template_category_callback(callback: CallbackQuery, state: FSMContext):
    """Backward-compat: redirect to flat template list for file processing"""
    templates = await template_service.get_all_templates()
    templates.sort(key=lambda t: (not t.is_default, t.name))

    keyboard_buttons = [
        [InlineKeyboardButton(
            text=t.name,
            callback_data=f"select_template_{t.id}"
        )] for t in templates
    ]
    keyboard_buttons.append([InlineKeyboardButton(
        text="⬅️ Назад",
        callback_data="back_to_template_categories"
    )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    await safe_edit_text(callback.message,
        "📝 **Выберите шаблон:**",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()
```

### Step 6: Remove `quick_category_callback` (around line 556)

Delete — no longer needed with 7 flat templates.

### Step 7: Commit

```bash
git add src/handlers/callbacks/template_callbacks.py
git commit -m "refactor: flatten template selection UI — remove category navigation"
```

---

## Task 4: Flatten template_mgmt_callbacks.py — Remove Category in Management

**Files:**
- Modify: `src/handlers/callbacks/template_mgmt_callbacks.py`

### Step 1: Flatten `view_template_category_callback` (lines 21-74)

Replace with flat list showing all templates for viewing:

```python
@router.callback_query(F.data.startswith("view_template_category_"))
async def view_template_category_callback(callback: CallbackQuery):
    """Backward-compat: show flat template list for viewing"""
    try:
        templates = await template_service.get_all_templates()
        templates.sort(key=lambda t: (not t.is_default, t.name))

        keyboard_buttons = [
            [InlineKeyboardButton(
                text=t.name,
                callback_data=f"view_template_{t.id}"
            )] for t in templates
        ]
        keyboard_buttons.append([InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="back_to_templates"
        )])

        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        await safe_edit_text(callback.message,
            f"📝 **Шаблоны** ({len(templates)})",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await callback.answer("❌ Ошибка при загрузке шаблонов")
```

### Step 2: Commit

```bash
git add src/handlers/callbacks/template_mgmt_callbacks.py
git commit -m "refactor: flatten template management UI — remove category filtering"
```

---

## Task 5: Flatten quick_actions.py — Remove Category in "Мои шаблоны"

**Files:**
- Modify: `src/ux/quick_actions.py`

### Step 1: Flatten `my_templates_button_handler` (around line 340-406)

Replace category grouping with flat list:

```python
# Replace lines 345-406 with:
templates.sort(key=lambda t: (not t.is_default, t.name))

keyboard_buttons = [
    [InlineKeyboardButton(
        text=t.name,
        callback_data=f"view_template_{t.id}"
    )] for t in templates
]

# Добавляем кнопку создания шаблона
keyboard_buttons.append([InlineKeyboardButton(
    text="➕ Добавить шаблон",
    callback_data="add_template"
)])

keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

await message.answer(
    f"📝 **Доступные шаблоны ({len(templates)}):**",
    reply_markup=keyboard,
    parse_mode="Markdown"
)
```

### Step 2: Commit

```bash
git add src/ux/quick_actions.py
git commit -m "refactor: flatten 'Мои шаблоны' UI — remove category grouping"
```

---

## Task 6: Clean Up smart_template_selector.py

**Files:**
- Modify: `src/services/smart_template_selector.py`

### Step 1: Simplify MEETING_TYPE_TO_CATEGORIES

With 7 templates, the mapping is simpler. Update the dict (lines 13-19):

```python
MEETING_TYPE_TO_CATEGORIES = {
    'technical': ['техническое', 'code review', 'разработка', 'архитектура', 'api'],
    'educational': ['лекция', 'обучение', 'презентация', 'тренинг'],
    'status': ['статус', 'стендап', 'ретроспектива', 'ежедневно', 'daily'],
    'management': ['поручение', 'задача', 'срок', 'ответственный', 'од'],
}
```

No further changes — the selector works on template embeddings which re-index on startup.

### Step 2: Commit

```bash
git add src/services/smart_template_selector.py
git commit -m "refactor: simplify smart selector categories for 7-template set"
```

---

## Task 7: Remove Category from template_service._get_default_templates()

**Files:**
- Modify: `src/services/template_service.py`

### Step 1: Remove `category` from default template dicts

In `_get_default_templates()` (line 209+), remove `"category": "general"` and `"category": "technical"` from all template dicts. Or set to `None`.

### Step 2: Remove category from `init_default_templates` sync logic

No changes needed — it syncs by name, not category.

### Step 3: Commit

```bash
git add src/services/template_service.py
git commit -m "refactor: remove category field from default template definitions"
```

---

## Task 8: Verify Everything Works

**Step 1: Run tests**

```bash
make test
```

Expected: All existing tests pass.

**Step 2: Check template count**

```bash
python -c "
import asyncio
from database import db
async def test():
    await db.init_db()
    import aiosqlite
    async with aiosqlite.connect('bot.db') as conn:
        cursor = await conn.execute('SELECT id, name FROM templates ORDER BY id')
        for row in await cursor.fetchall():
            print(f'{row[0]}: {row[1]}')
asyncio.run(test())
"
```

Expected output:
```
1: Стандартный протокол встречи
2: Краткое резюме встречи
3: Техническое совещание
15: Sprint Retrospective
17: Daily Standup
22: Протокол ОД (Поручения)
23: Лекция и презентация
```

**Step 3: Start bot and test manually**

```bash
python main.py
```

Test in Telegram:
1. Send a file — template selection should show flat list of 7
2. `/start` → "Мои шаблоны" — should show flat list without categories
3. Settings → "Шаблон по умолчанию" — should show flat list

**Step 4: Final commit (if any fixes needed)**

```bash
git add -A
git commit -m "fix: template consolidation polish"
```
