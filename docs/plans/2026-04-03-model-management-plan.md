# Model Management Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable admins to add, remove, and configure any OpenAI-compatible model (including OpenRouter) from the Telegram bot interface, with per-preset API keys and user access control.

**Architecture:** New `model_presets` table in SQLite with a repository layer. Admin commands (`/add_model`, `/models`) for CRUD. OpenAIProvider gets a client cache for per-preset `base_url`/`api_key`. Settings UI reads presets from DB instead of config. On startup, `.env` presets sync into DB.

**Tech Stack:** Python 3.11+, aiogram 3.x, aiosqlite, OpenAI SDK

---

### Task 1: Database — model_presets table

**Files:**
- Modify: `src/database/database.py:17` — add CREATE TABLE in `init_db()`
- Create: `src/database/model_preset_repo.py`

**Step 1: Add table creation to `init_db()`**

In `src/database/database.py`, inside `init_db()`, after the existing CREATE TABLE statements, add:

```python
            # Таблица пресетов моделей
            await db.execute("""
                CREATE TABLE IF NOT EXISTS model_presets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    model TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    api_key TEXT,
                    admin_only BOOLEAN DEFAULT 0,
                    is_enabled BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
```

**Step 2: Create `src/database/model_preset_repo.py`**

Follow the pattern from `src/database/user_repo.py`:

```python
"""Model preset data access."""
import aiosqlite
from typing import Optional, List, Dict, Any
from loguru import logger


class ModelPresetRepository:
    """Repository for model preset CRUD operations."""

    def __init__(self, database):
        self._db = database

    async def get_all(self) -> List[Dict[str, Any]]:
        """Get all model presets."""
        async with aiosqlite.connect(self._db.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM model_presets ORDER BY created_at"
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_enabled(self) -> List[Dict[str, Any]]:
        """Get enabled presets."""
        async with aiosqlite.connect(self._db.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM model_presets WHERE is_enabled = 1 ORDER BY created_at"
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_available_for_user(self, user_id: int) -> List[Dict[str, Any]]:
        """Get presets available to a specific user (filters admin_only)."""
        from src.utils.admin_utils import is_admin
        presets = await self.get_enabled()
        if is_admin(user_id):
            return presets
        return [p for p in presets if not p['admin_only']]

    async def get_by_key(self, key: str) -> Optional[Dict[str, Any]]:
        """Get preset by key."""
        async with aiosqlite.connect(self._db.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM model_presets WHERE key = ?", (key,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def upsert(self, key: str, name: str, model: str, base_url: str,
                     api_key: str = None, admin_only: bool = False) -> int:
        """Insert or update a preset by key."""
        async with aiosqlite.connect(self._db.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO model_presets (key, name, model, base_url, api_key, admin_only)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    name = excluded.name,
                    model = excluded.model,
                    base_url = excluded.base_url,
                    api_key = COALESCE(excluded.api_key, model_presets.api_key),
                    admin_only = excluded.admin_only
            """, (key, name, model, base_url, api_key, admin_only))
            await db.commit()
            return cursor.lastrowid

    async def update_field(self, key: str, field: str, value: Any) -> bool:
        """Update a single field on a preset."""
        allowed_fields = {'name', 'model', 'base_url', 'api_key', 'admin_only', 'is_enabled'}
        if field not in allowed_fields:
            raise ValueError(f"Field {field} not allowed")
        async with aiosqlite.connect(self._db.db_path) as db:
            cursor = await db.execute(
                f"UPDATE model_presets SET {field} = ? WHERE key = ?",
                (value, key)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def delete(self, key: str) -> bool:
        """Delete a preset by key."""
        async with aiosqlite.connect(self._db.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM model_presets WHERE key = ?", (key,)
            )
            await db.commit()
            return cursor.rowcount > 0
```

**Step 3: Verify syntax**

Run: `python -m py_compile src/database/model_preset_repo.py`

**Step 4: Commit**

```bash
git add src/database/database.py src/database/model_preset_repo.py
git commit -m "feat: model_presets table and repository"
```

---

### Task 2: Startup sync — import .env presets into DB

**Files:**
- Modify: `src/bot.py` — add sync call during startup

**Step 1: Create sync function**

Add to `src/database/model_preset_repo.py`:

```python
    async def sync_from_config(self) -> int:
        """Import presets from settings.openai_models into DB. Returns count synced."""
        from config import settings
        count = 0
        for preset in settings.openai_models:
            await self.upsert(
                key=preset.key,
                name=preset.name,
                model=preset.model,
                base_url=preset.base_url or settings.openai_base_url or "https://api.openai.com/v1",
            )
            count += 1
        logger.info(f"Синхронизировано {count} пресетов моделей из конфигурации")
        return count
```

**Step 2: Add sync call to bot startup**

In `src/bot.py`, find the `start()` or `__init__` method where `db.init_db()` is called. After that call, add:

```python
from src.database.model_preset_repo import ModelPresetRepository
model_preset_repo = ModelPresetRepository(db)
await model_preset_repo.sync_from_config()
```

Also expose `model_preset_repo` so handlers can import it. Add to `src/database/__init__.py` or create a module-level instance like the existing `db` singleton.

**Step 3: Verify syntax**

Run: `python -m py_compile src/bot.py`

**Step 4: Commit**

```bash
git add src/database/model_preset_repo.py src/bot.py
git commit -m "feat: sync .env model presets into DB on startup"
```

---

### Task 3: Admin commands — /add_model and /models

**Files:**
- Modify: `src/handlers/admin_handlers.py` — add new handlers
- Use FSM for editing dialogs

**Step 1: Add `/add_model` command handler**

In `src/handlers/admin_handlers.py`, inside `setup_admin_handlers()`, add:

```python
    @router.message(Command("add_model"))
    async def add_model_handler(message: Message):
        """Add a new model preset. Format: /add_model <model_id> "<name>" <base_url> [api_key]"""
        if not is_admin(message.from_user.id):
            await message.answer("❌ Недостаточно прав.")
            return

        import re
        args = message.text.replace("/add_model", "", 1).strip()
        if not args:
            await message.answer(
                "📝 Формат: `/add_model model_id \"Название\" base_url [api_key]`\n\n"
                "Пример:\n"
                "`/add_model google/gemini-2.0-flash \"Gemini Flash\" https://openrouter.ai/api/v1`",
                parse_mode="Markdown"
            )
            return

        # Parse: model_id "name" base_url [api_key]
        match = re.match(r'(\S+)\s+"([^"]+)"\s+(\S+)(?:\s+(\S+))?', args)
        if not match:
            await message.answer("❌ Неверный формат. Используй: `/add_model model_id \"Название\" base_url [api_key]`", parse_mode="Markdown")
            return

        model_id, name, base_url, api_key = match.groups()
        key = re.sub(r'[^a-zA-Z0-9_-]', '_', model_id)

        from src.database.model_preset_repo import ModelPresetRepository
        from database import db
        repo = ModelPresetRepository(db)
        await repo.upsert(key=key, name=name, model=model_id, base_url=base_url, api_key=api_key)

        await message.answer(
            f"✅ Модель добавлена:\n\n"
            f"📌 **{name}**\n"
            f"Model: `{model_id}`\n"
            f"URL: `{base_url}`\n"
            f"API Key: {'✅ задан' if api_key else '🔑 глобальный'}\n"
            f"Key: `{key}`",
            parse_mode="Markdown"
        )
```

**Step 2: Add `/models` command handler with inline keyboard**

```python
    @router.message(Command("models"))
    async def models_handler(message: Message):
        """List and manage model presets."""
        if not is_admin(message.from_user.id):
            await message.answer("❌ Недостаточно прав.")
            return

        from src.database.model_preset_repo import ModelPresetRepository
        from database import db
        repo = ModelPresetRepository(db)
        presets = await repo.get_all()

        if not presets:
            await message.answer("Нет настроенных моделей. Используй /add_model для добавления.")
            return

        lines = ["📋 **Модели:**\n"]
        keyboard_rows = []
        for i, p in enumerate(presets, 1):
            status = "✅" if p['is_enabled'] else "⛔"
            access = " 🔒" if p['admin_only'] else ""
            lines.append(f"{i}. {status} **{p['name']}**{access}\n   `{p['model']}`")
            keyboard_rows.append([InlineKeyboardButton(
                text=f"{status} {p['name']}",
                callback_data=f"admin_model_{p['key']}"
            )])

        keyboard_rows.append([
            InlineKeyboardButton(text="🔄 Синхр. из .env", callback_data="admin_models_sync")
        ])

        await message.answer(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        )
```

**Step 3: Add callback handlers for model detail card and actions**

```python
    @router.callback_query(F.data.startswith("admin_model_"))
    async def admin_model_detail_callback(callback: CallbackQuery):
        """Show model detail card with action buttons."""
        if not is_admin(callback.from_user.id):
            await callback.answer("❌ Недостаточно прав.")
            return

        key = callback.data.replace("admin_model_", "")
        from src.database.model_preset_repo import ModelPresetRepository
        from database import db
        repo = ModelPresetRepository(db)
        p = await repo.get_by_key(key)

        if not p:
            await callback.answer("Модель не найдена")
            return

        status = "✅ включена" if p['is_enabled'] else "⛔ выключена"
        access = "🔒 только админы" if p['admin_only'] else "👥 все пользователи"
        api_info = "🔑 свой ключ" if p['api_key'] else "🌐 глобальный"

        text = (
            f"**{p['name']}**\n\n"
            f"Model: `{p['model']}`\n"
            f"URL: `{p['base_url']}`\n"
            f"API Key: {api_info}\n"
            f"Статус: {status}\n"
            f"Доступ: {access}"
        )

        toggle_enabled = "✅ Включить" if not p['is_enabled'] else "⛔ Выключить"
        toggle_access = "👥 Для всех" if p['admin_only'] else "🔒 Только админы"

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=toggle_enabled, callback_data=f"admin_model_toggle_{key}"),
                InlineKeyboardButton(text=toggle_access, callback_data=f"admin_model_access_{key}"),
            ],
            [
                InlineKeyboardButton(text="🗑 Удалить", callback_data=f"admin_model_delete_{key}"),
            ],
            [InlineKeyboardButton(text="⬅️ К списку", callback_data="admin_models_list")],
        ])

        await safe_edit_text(callback.message, text, reply_markup=keyboard, parse_mode="Markdown")
        await callback.answer()

    @router.callback_query(F.data.startswith("admin_model_toggle_"))
    async def admin_model_toggle_callback(callback: CallbackQuery):
        """Toggle model enabled/disabled."""
        if not is_admin(callback.from_user.id):
            await callback.answer("❌ Недостаточно прав.")
            return
        key = callback.data.replace("admin_model_toggle_", "")
        from src.database.model_preset_repo import ModelPresetRepository
        from database import db
        repo = ModelPresetRepository(db)
        p = await repo.get_by_key(key)
        if p:
            await repo.update_field(key, "is_enabled", not p['is_enabled'])
        # Re-render detail card
        callback.data = f"admin_model_{key}"
        await admin_model_detail_callback(callback)

    @router.callback_query(F.data.startswith("admin_model_access_"))
    async def admin_model_access_callback(callback: CallbackQuery):
        """Toggle model admin_only flag."""
        if not is_admin(callback.from_user.id):
            await callback.answer("❌ Недостаточно прав.")
            return
        key = callback.data.replace("admin_model_access_", "")
        from src.database.model_preset_repo import ModelPresetRepository
        from database import db
        repo = ModelPresetRepository(db)
        p = await repo.get_by_key(key)
        if p:
            await repo.update_field(key, "admin_only", not p['admin_only'])
        callback.data = f"admin_model_{key}"
        await admin_model_detail_callback(callback)

    @router.callback_query(F.data.startswith("admin_model_delete_"))
    async def admin_model_delete_callback(callback: CallbackQuery):
        """Delete a model preset."""
        if not is_admin(callback.from_user.id):
            await callback.answer("❌ Недостаточно прав.")
            return
        key = callback.data.replace("admin_model_delete_", "")
        from src.database.model_preset_repo import ModelPresetRepository
        from database import db
        repo = ModelPresetRepository(db)
        await repo.delete(key)
        await callback.answer(f"🗑 Модель {key} удалена")
        # Return to list
        callback.data = "admin_models_list"
        await admin_models_list_callback(callback)

    @router.callback_query(F.data == "admin_models_sync")
    async def admin_models_sync_callback(callback: CallbackQuery):
        """Sync presets from .env into DB."""
        if not is_admin(callback.from_user.id):
            await callback.answer("❌ Недостаточно прав.")
            return
        from src.database.model_preset_repo import ModelPresetRepository
        from database import db
        repo = ModelPresetRepository(db)
        count = await repo.sync_from_config()
        await callback.answer(f"🔄 Синхронизировано {count} моделей из .env")
        callback.data = "admin_models_list"
        await admin_models_list_callback(callback)

    @router.callback_query(F.data == "admin_models_list")
    async def admin_models_list_callback(callback: CallbackQuery):
        """Re-render model list (callback version of /models)."""
        if not is_admin(callback.from_user.id):
            await callback.answer("❌ Недостаточно прав.")
            return
        from src.database.model_preset_repo import ModelPresetRepository
        from database import db
        repo = ModelPresetRepository(db)
        presets = await repo.get_all()

        if not presets:
            await safe_edit_text(callback.message, "Нет настроенных моделей.")
            await callback.answer()
            return

        lines = ["📋 **Модели:**\n"]
        keyboard_rows = []
        for i, p in enumerate(presets, 1):
            status = "✅" if p['is_enabled'] else "⛔"
            access = " 🔒" if p['admin_only'] else ""
            lines.append(f"{i}. {status} **{p['name']}**{access}\n   `{p['model']}`")
            keyboard_rows.append([InlineKeyboardButton(
                text=f"{status} {p['name']}",
                callback_data=f"admin_model_{p['key']}"
            )])
        keyboard_rows.append([
            InlineKeyboardButton(text="🔄 Синхр. из .env", callback_data="admin_models_sync")
        ])

        await safe_edit_text(
            callback.message,
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_rows),
            parse_mode="Markdown"
        )
        await callback.answer()
```

**Step 4: Update admin help text**

In `admin_help_handler` (line 298), add to help_text:

```
**Управление моделями:**
• `/models` - список и управление моделями
• `/add_model` - добавить модель
```

**Step 5: Verify syntax**

Run: `python -m py_compile src/handlers/admin_handlers.py`

**Step 6: Commit**

```bash
git add src/handlers/admin_handlers.py
git commit -m "feat: admin commands /add_model and /models with inline UI"
```

---

### Task 4: OpenAIProvider — per-preset client cache

**Files:**
- Modify: `src/llm/providers/openai_provider.py:21-77` — add client cache, use preset base_url/api_key

**Step 1: Add client cache to `__init__`**

Replace `__init__` (lines 24-34):

```python
    def __init__(self):
        self.default_client = None
        self.http_client = None
        self._client_cache = {}  # (base_url, api_key_hash) -> openai.OpenAI
        if settings.openai_api_key:
            openai.api_key = settings.openai_api_key
            self.http_client = httpx.Client(verify=settings.ssl_verify, timeout=settings.llm_timeout_seconds)
            self.default_client = openai.OpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                http_client=self.http_client
            )
```

**Step 2: Add `_get_client` method**

```python
    def _get_client(self, preset: dict = None) -> openai.OpenAI:
        """Get or create an OpenAI client for the given preset."""
        if not preset:
            return self.default_client

        base_url = preset.get('base_url') or settings.openai_base_url
        api_key = preset.get('api_key') or settings.openai_api_key

        cache_key = (base_url, hash(api_key) if api_key else None)

        if cache_key not in self._client_cache:
            http_client = httpx.Client(verify=settings.ssl_verify, timeout=settings.llm_timeout_seconds)
            self._client_cache[cache_key] = openai.OpenAI(
                api_key=api_key,
                base_url=base_url,
                http_client=http_client,
            )
            logger.info(f"Создан клиент для {base_url}")

        return self._client_cache[cache_key]
```

**Step 3: Update `generate_protocol` to resolve preset from DB**

Replace lines 67-77 (model selection block):

```python
        selected_model = settings.openai_model
        openai_model_key = kwargs.get('openai_model_key')
        preset_dict = None

        if openai_model_key:
            try:
                # Try DB first, fall back to config
                import asyncio
                from src.database.model_preset_repo import ModelPresetRepository
                from database import db
                repo = ModelPresetRepository(db)
                preset_dict = await repo.get_by_key(openai_model_key)

                if preset_dict:
                    selected_model = preset_dict['model']
                    logger.info(f"Используется модель из БД: {selected_model} (ключ: {openai_model_key})")
                else:
                    # Fallback to config presets
                    preset = next((p for p in settings.openai_models if p.key == openai_model_key), None)
                    if preset:
                        selected_model = preset.model
                        preset_dict = {'base_url': preset.base_url, 'api_key': None}
                        logger.info(f"Используется модель из конфига: {selected_model} (ключ: {openai_model_key})")
            except Exception as e:
                logger.warning(f"Не удалось определить модель по ключу {openai_model_key}: {e}")
```

**Step 4: Update `_call_openai` to accept a client**

Change `_call_openai` signature (line 141) to accept optional `client` parameter:

```python
    async def _call_openai(self, system_prompt: str, user_prompt: str, schema: Dict[str, Any],
                           step_name: str, model: str = None, client: openai.OpenAI = None) -> Dict[str, Any]:
        """Helper method for OpenAI API calls."""
        selected_model = model or settings.openai_model
        active_client = client or self.default_client
```

Then replace `self.client.chat.completions.create` with `active_client.chat.completions.create` in `_api_call()` (line 155-156).

**Step 5: Pass client to `_call_openai` calls**

In `generate_protocol()`, when calling `_call_openai` for Stage 2 (line 122):

```python
        client = self._get_client(preset_dict)

        generation_result = await self._call_openai(
            system_prompt=generation_system_prompt,
            user_prompt=generation_user_prompt,
            schema=PROTOCOL_DATA_SCHEMA,
            step_name="Generation",
            model=selected_model,
            client=client
        )
```

Stage 1 analysis uses `settings.analysis_stage_model` (not user preset), so no client override needed.

**Step 6: Update `is_available`**

```python
    def is_available(self) -> bool:
        return self.default_client is not None and settings.openai_api_key is not None
```

**Step 7: Verify syntax**

Run: `python -m py_compile src/llm/providers/openai_provider.py`

**Step 8: Commit**

```bash
git add src/llm/providers/openai_provider.py
git commit -m "feat: per-preset client cache in OpenAIProvider"
```

---

### Task 5: Settings UI — read presets from DB

**Files:**
- Modify: `src/handlers/callbacks/settings_callbacks.py:52-87` — load from DB with access filtering

**Step 1: Update `settings_openai_model_callback`**

Replace lines 52-87 to load from DB:

```python
    @router.callback_query(F.data == "settings_openai_model")
    async def settings_openai_model_callback(callback: CallbackQuery):
        """Обработчик меню выбора модели OpenAI"""
        try:
            from src.database.model_preset_repo import ModelPresetRepository
            from database import db as app_db
            repo = ModelPresetRepository(app_db)
            presets = await repo.get_available_for_user(callback.from_user.id)

            if not presets:
                await safe_edit_text(callback.message,
                    "❌ Нет доступных моделей.\n\n"
                    "Администратор может добавить модели командой /add_model.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="⬅️ Назад к настройкам", callback_data="back_to_settings")]
                    ])
                )
                await callback.answer()
                return

            user = await user_service.get_user_by_telegram_id(callback.from_user.id)
            selected_key = getattr(user, 'preferred_openai_model_key', None) if user else None

            keyboard_rows = []
            for p in presets:
                label = f"{'✅ ' if selected_key == p['key'] else ''}{p['name']}"
                keyboard_rows.append([InlineKeyboardButton(text=label, callback_data=f"set_openai_model_{p['key']}")])
            keyboard_rows.append([InlineKeyboardButton(text="🔄 Сбросить выбор модели", callback_data="reset_openai_model_preference")])
            keyboard_rows.append([InlineKeyboardButton(text="⬅️ Назад к настройкам", callback_data="back_to_settings")])

            await safe_edit_text(callback.message,
                "🧠 **Модель OpenAI**\n\n"
                "Выберите модель:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
            )
            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка в settings_openai_model_callback: {e}")
            await callback.answer("❌ Не удалось загрузить модели OpenAI")
```

**Step 2: Update `set_openai_model_callback`**

Replace lines 89-112 to look up name from DB:

```python
    @router.callback_query(F.data.startswith("set_openai_model_"))
    async def set_openai_model_callback(callback: CallbackQuery):
        """Устанавливает предпочитаемую модель OpenAI"""
        try:
            model_key = callback.data.replace("set_openai_model_", "")
            await user_service.update_user_openai_model_preference(callback.from_user.id, model_key)

            # Get display name from DB
            from src.database.model_preset_repo import ModelPresetRepository
            from database import db as app_db
            repo = ModelPresetRepository(app_db)
            preset = await repo.get_by_key(model_key)
            model_name = preset['name'] if preset else model_key

            await safe_edit_text(callback.message,
                f"✅ Модель обновлена: {model_name}.\n\n"
                "Она будет использоваться при выборе провайдера OpenAI.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад к настройкам", callback_data="back_to_settings")]
                ])
            )
            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка в set_openai_model_callback: {e}")
            await callback.answer("❌ Не удалось сохранить выбор модели")
```

**Step 3: Verify syntax**

Run: `python -m py_compile src/handlers/callbacks/settings_callbacks.py`

**Step 4: Commit**

```bash
git add src/handlers/callbacks/settings_callbacks.py
git commit -m "feat: settings UI reads model presets from DB"
```

---

### Task 6: LLM generation — resolve preset display name from DB

**Files:**
- Modify: `src/services/processing/llm_generation.py` — update `_get_model_display_name` or equivalent

**Step 1: Find where display name is resolved**

Grep for `get_model_display_name` in `src/services/processing/` and update to check DB first:

```python
# In the method that resolves display name:
from src.database.model_preset_repo import ModelPresetRepository
from database import db
repo = ModelPresetRepository(db)
preset = await repo.get_by_key(openai_model_key)
if preset:
    return preset['name']
# else fall back to config lookup
```

**Step 2: Handle deleted preset gracefully**

If user has `preferred_openai_model_key` pointing to a deleted preset, fall back to default model. This already works because the DB lookup returns None and the existing fallback logic applies.

**Step 3: Verify syntax**

**Step 4: Commit**

```bash
git add src/services/processing/llm_generation.py
git commit -m "feat: resolve model display name from DB"
```

---

## Verification Plan

After all tasks:

1. **Bot starts**: `python main.py` — no errors, presets synced from .env
2. **Admin adds model**: `/add_model google/gemini-2.0-flash "Gemini Flash" https://openrouter.ai/api/v1` — confirms success
3. **Admin lists models**: `/models` — shows all presets with inline buttons
4. **Admin toggles access**: Click model → toggle "только админы" → verify non-admin doesn't see it
5. **Admin disables model**: Click model → "Выключить" → verify removed from user settings
6. **Admin deletes model**: Click model → "Удалить" → verify removed from list
7. **User selects model**: Settings → Модель → sees only available models
8. **Processing works**: Upload audio, select OpenRouter model → protocol generated via correct API endpoint
9. **Sync works**: Click "Синхр. из .env" → presets from .env re-imported
10. **Fallback works**: Delete user's selected preset → processing uses default model
