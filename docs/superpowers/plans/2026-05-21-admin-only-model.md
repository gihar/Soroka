# Admin-only AI Model Selection — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move AI model selection from per-user settings into a single, global, admin-only setting; remove Anthropic/Yandex providers and the per-user model preference path.

**Architecture:** A new `app_settings` key-value table stores `active_model_key` referencing `model_presets`. `LLMManager` keeps only `OpenAIProvider` and exposes `generate_protocol(preset=…)`. Processing-time resolution reads `app_settings.active_model_key` on every request; the UI shows the model picker only to admins.

**Tech Stack:** Python 3.10+, aiogram 3.x, aiosqlite, Pydantic v2, pytest, pytest-asyncio.

**Spec:** [`docs/superpowers/specs/2026-05-21-admin-only-model-design.md`](../specs/2026-05-21-admin-only-model-design.md)

---

## Conventions used throughout

- All commands are run from the repo root `/Users/timchenko/Soroka`.
- Tests live flat in `tests/`. The shared fixture `test_db` (in `tests/conftest.py`) creates a temporary SQLite DB and runs `init_db`, so any new table inside `init_db` is automatically available in tests.
- Commits use Conventional Commits format with bodies omitted for small steps (`feat:`, `refactor:`, `test:`, `chore:`).
- When a task deletes code, the "failing test" step is replaced with **"Run the full test suite to capture the green baseline"**, and the final step verifies the suite is still green.

---

## File Structure

### New files

| File | Responsibility |
|---|---|
| `src/exceptions/configuration.py` | Two exception classes: `AdminConfigurationError`, `ActivePresetDeletionError` (both inherit `BotException`). |
| `src/database/app_settings_repo.py` | `AppSettingsRepository` — generic key-value access + typed helper for `active_model_key`. |
| `tests/test_app_settings_init.py` | Tests for `app_settings` table creation and seed. |
| `tests/test_app_settings_repo.py` | Unit tests for `AppSettingsRepository`. |
| `tests/test_model_preset_active_guards.py` | Unit tests for the new delete/disable guards in `ModelPresetRepository`. |
| `tests/test_openai_provider.py` | Tests for OpenAIProvider preset handling + cache invalidation. |
| `tests/test_enhanced_llm_service.py` | Tests for the simplified, single-provider EnhancedLLMService. |
| `tests/test_active_model_resolver.py` | Tests for `resolve_active_preset` helper. |
| `tests/test_settings_menu.py` | Tests for the `is_admin`-aware settings menu. |

### Modified files

| File | Why |
|---|---|
| `src/exceptions/__init__.py` | Re-export new exception classes. |
| `src/database/database.py` | Add `app_settings` table + seed in `init_db`; remove `update_user_llm_preference`, `update_user_openai_model_preference`. |
| `src/database/user_repo.py` | Remove `update_llm_preference`, `update_openai_model_preference`. |
| `src/database/model_preset_repo.py` | Guard `delete` and disable-via-`update_field` against the active preset. |
| `src/llm/manager.py` | Drop Anthropic/Yandex; new `generate_protocol(preset=…)` signature; remove `generate_protocol_with_fallback`. |
| `src/llm/providers/openai_provider.py` | Accept `preset` argument directly; expose `invalidate_cache_for(...)`; drop `openai_model_key` kwarg lookup. |
| `src/llm/providers/__init__.py` | Drop Anthropic/Yandex from exports. |
| `src/services/enhanced_llm_service.py` | Drop multi-provider fallback chain; single OpenAI provider + reliability stack; new `generate_protocol_with_preset(preset, …)`. |
| `src/services/processing/llm_generation.py` | Resolve `active_model_key` instead of `user.preferred_openai_model_key`; switch to new EnhancedLLMService API. |
| `src/services/processing/processing_service.py` | Use active-model resolver for `llm_model_used` display name. |
| `src/services/user_service.py` | Remove `update_user_llm_preference`, `update_user_openai_model_preference`. |
| `src/ux/quick_actions.py` | `create_settings_menu(is_admin: bool)`. |
| `src/handlers/callbacks/settings_callbacks.py` | New `settings_active_model` + `set_active_model_<key>` callbacks; remove old per-user model/provider callbacks. |
| `src/handlers/callbacks/__init__.py` | Stop wiring `llm_callbacks`. |
| `src/handlers/admin_handlers.py` | `_render_models_list` and `_render_model_detail` show ⭐ on active; add "▶️ Сделать активной" button; delete-/toggle-callbacks translate `ActivePresetDeletionError` to user message. |
| `src/handlers/command_handlers.py` | `/start` and `/settings` text — admin sees active model name, non-admin sees no model line. |
| `src/handlers/message_handlers.py` | Drop LLM selection UI; proceed directly to processing. |
| `src/bot.py` | Stop registering `setup_llm_callbacks`. |
| `src/config.py` | Remove `anthropic_api_key`, `yandex_api_key`, `yandex_folder_id`. |
| `main.py` | Drop the Anthropic/Yandex check on startup. |
| `env_example` | Remove Anthropic/Yandex variables. |
| `tests/test_database_repos.py` | Remove `test_update_llm_preference`, `test_update_openai_model_preference`. |
| `tests/test_llm_manager.py` | Update fake-module shim (no Anthropic/Yandex) + new `generate_protocol(preset=…)` signature. |
| `tests/conftest.py` | New fixture `app_settings_repo(test_db)`. |

### Deleted files

| File | Why |
|---|---|
| `src/llm/providers/anthropic_provider.py` | Provider removed. |
| `src/llm/providers/yandex_provider.py` | Provider removed. |
| `src/handlers/callbacks/llm_callbacks.py` | All routes removed (per-user provider/model selection). |

---

# Tasks

## Stage A — Foundation (additive)

### Task 1: Add new exception classes

**Files:**
- Create: `src/exceptions/configuration.py`
- Modify: `src/exceptions/__init__.py`

- [ ] **Step 1: Write the file**

Create `src/exceptions/configuration.py` with content:

```python
"""
Исключения для конфигурации и админских операций.
"""

from src.exceptions.base import BotException


class AdminConfigurationError(BotException):
    """Операция невозможна, потому что админ-настройка отсутствует
    или некорректна (например, не выбрана активная модель)."""


class ActivePresetDeletionError(BotException):
    """Попытка удалить или отключить пресет, который сейчас выбран
    как активная модель бота."""
```

- [ ] **Step 2: Re-export from package `__init__`**

Open `src/exceptions/__init__.py` and add the line:

```python
from .configuration import AdminConfigurationError, ActivePresetDeletionError
```

(Place it next to the other relative imports — order does not matter.)

- [ ] **Step 3: Verify imports work**

Run: `python -c "from src.exceptions import AdminConfigurationError, ActivePresetDeletionError; e = AdminConfigurationError('test'); print(e)"`
Expected output: `test`

- [ ] **Step 4: Commit**

```bash
git add src/exceptions/configuration.py src/exceptions/__init__.py
git commit -m "feat(exceptions): add AdminConfigurationError and ActivePresetDeletionError"
```

---

### Task 2: Create `app_settings` table and seed in `init_db`

**Files:**
- Modify: `src/database/database.py`
- Create: `tests/test_app_settings_init.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_app_settings_init.py`:

```python
"""Tests for app_settings table creation and seed during init_db."""
import pytest
import aiosqlite


@pytest.mark.asyncio
async def test_app_settings_table_exists(test_db):
    """init_db creates app_settings table."""
    async with aiosqlite.connect(test_db.db_path) as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='app_settings'"
        )
        row = await cursor.fetchone()
        assert row is not None, "app_settings table was not created"


@pytest.mark.asyncio
async def test_app_settings_seed_skipped_when_no_presets(test_db):
    """When no enabled presets exist, active_model_key is NOT seeded."""
    async with aiosqlite.connect(test_db.db_path) as db:
        cursor = await db.execute(
            "SELECT value FROM app_settings WHERE key = 'active_model_key'"
        )
        row = await cursor.fetchone()
        assert row is None, "Should not seed when no enabled presets"


@pytest.mark.asyncio
async def test_app_settings_seeds_first_enabled_preset(tmp_path):
    """When init_db runs and presets exist, the first enabled preset key is seeded."""
    from src.database.database import Database
    db_path = str(tmp_path / "test.db")
    db = Database(db_path=db_path)
    await db.init_db()

    # Insert enabled preset manually, then re-run init_db (idempotent)
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO model_presets (key, name, model, base_url, is_enabled) VALUES (?, ?, ?, ?, 1)",
            ("seed_key", "Seed Model", "gpt-4o-mini", "https://api.openai.com/v1"),
        )
        await conn.commit()

    await db.init_db()  # second call should seed active_model_key

    async with aiosqlite.connect(db_path) as conn:
        cursor = await conn.execute(
            "SELECT value FROM app_settings WHERE key = 'active_model_key'"
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "seed_key"


@pytest.mark.asyncio
async def test_app_settings_seed_is_idempotent(tmp_path):
    """Re-running init_db does not overwrite an existing active_model_key."""
    from src.database.database import Database
    db_path = str(tmp_path / "test.db")
    db = Database(db_path=db_path)
    await db.init_db()

    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO model_presets (key, name, model, base_url, is_enabled) VALUES (?, ?, ?, ?, 1)",
            ("first", "First", "m1", "u1"),
        )
        await conn.execute(
            "INSERT INTO model_presets (key, name, model, base_url, is_enabled) VALUES (?, ?, ?, ?, 1)",
            ("second", "Second", "m2", "u2"),
        )
        await conn.execute(
            "INSERT INTO app_settings (key, value, updated_by) VALUES ('active_model_key', 'second', 42)"
        )
        await conn.commit()

    await db.init_db()

    async with aiosqlite.connect(db_path) as conn:
        cursor = await conn.execute(
            "SELECT value, updated_by FROM app_settings WHERE key = 'active_model_key'"
        )
        row = await cursor.fetchone()
        assert row[0] == "second"
        assert row[1] == 42
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_app_settings_init.py -v`
Expected: All 4 tests FAIL — `app_settings` table does not exist.

- [ ] **Step 3: Implement table creation and seed**

In `src/database/database.py`, inside `init_db`, immediately after the existing `model_presets` `CREATE TABLE IF NOT EXISTS` block (around line 232, before `_consolidate_templates`), add:

```python
            # Таблица глобальных настроек приложения (key-value)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_by INTEGER
                )
            """)

            # Seed active_model_key from first enabled preset (idempotent)
            cursor = await db.execute(
                "SELECT value FROM app_settings WHERE key = 'active_model_key'"
            )
            existing = await cursor.fetchone()
            if existing is None:
                cursor = await db.execute(
                    "SELECT key FROM model_presets WHERE is_enabled = 1 "
                    "ORDER BY created_at LIMIT 1"
                )
                preset_row = await cursor.fetchone()
                if preset_row is not None:
                    await db.execute(
                        "INSERT INTO app_settings (key, value, updated_by) "
                        "VALUES ('active_model_key', ?, NULL)",
                        (preset_row[0],),
                    )
                    logger.info(
                        f"Seeded active_model_key = '{preset_row[0]}' "
                        "from first enabled preset"
                    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_app_settings_init.py -v`
Expected: 4 passed.

- [ ] **Step 5: Run the full test suite to confirm no regressions**

Run: `pytest tests/ -x -q`
Expected: All previously passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add src/database/database.py tests/test_app_settings_init.py
git commit -m "feat(db): add app_settings table and seed active_model_key"
```

---

### Task 3: Create `AppSettingsRepository`

**Files:**
- Create: `src/database/app_settings_repo.py`
- Create: `tests/test_app_settings_repo.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_app_settings_repo.py`:

```python
"""Tests for AppSettingsRepository."""
import pytest
from src.exceptions.configuration import AdminConfigurationError


@pytest.mark.asyncio
async def test_get_returns_none_for_missing_key(app_settings_repo):
    result = await app_settings_repo.get("nonexistent_key")
    assert result is None


@pytest.mark.asyncio
async def test_set_inserts_new_row(app_settings_repo):
    await app_settings_repo.set("custom_key", "custom_value", admin_id=42)
    result = await app_settings_repo.get("custom_key")
    assert result == "custom_value"


@pytest.mark.asyncio
async def test_set_upserts_existing_row(app_settings_repo):
    await app_settings_repo.set("custom_key", "first", admin_id=42)
    await app_settings_repo.set("custom_key", "second", admin_id=43)
    result = await app_settings_repo.get("custom_key")
    assert result == "second"


@pytest.mark.asyncio
async def test_get_active_model_key_returns_none_initially(app_settings_repo, test_db):
    """Empty DB has no enabled presets, so init_db skips seeding."""
    result = await app_settings_repo.get_active_model_key()
    assert result is None


@pytest.mark.asyncio
async def test_set_active_model_key_rejects_missing_preset(app_settings_repo):
    with pytest.raises(AdminConfigurationError):
        await app_settings_repo.set_active_model_key("does_not_exist", admin_id=42)


@pytest.mark.asyncio
async def test_set_active_model_key_rejects_disabled_preset(app_settings_repo, test_db):
    import aiosqlite
    async with aiosqlite.connect(test_db.db_path) as db:
        await db.execute(
            "INSERT INTO model_presets (key, name, model, base_url, is_enabled) "
            "VALUES (?, ?, ?, ?, 0)",
            ("disabled_key", "Disabled", "m", "u"),
        )
        await db.commit()

    with pytest.raises(AdminConfigurationError):
        await app_settings_repo.set_active_model_key("disabled_key", admin_id=42)


@pytest.mark.asyncio
async def test_set_active_model_key_accepts_enabled_preset(app_settings_repo, test_db):
    import aiosqlite
    async with aiosqlite.connect(test_db.db_path) as db:
        await db.execute(
            "INSERT INTO model_presets (key, name, model, base_url, is_enabled) "
            "VALUES (?, ?, ?, ?, 1)",
            ("ok_key", "OK", "m", "u"),
        )
        await db.commit()

    await app_settings_repo.set_active_model_key("ok_key", admin_id=42)
    assert await app_settings_repo.get_active_model_key() == "ok_key"
```

Append to `tests/conftest.py`:

```python
@pytest.fixture
async def app_settings_repo(test_db):
    """AppSettingsRepository backed by the test DB."""
    from src.database.app_settings_repo import AppSettingsRepository
    return AppSettingsRepository(test_db)
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `pytest tests/test_app_settings_repo.py -v`
Expected: All tests FAIL with `ModuleNotFoundError: No module named 'src.database.app_settings_repo'`.

- [ ] **Step 3: Implement `AppSettingsRepository`**

Create `src/database/app_settings_repo.py`:

```python
"""Application-wide key-value settings (admin-controlled).

Stores small, global pieces of state that are not user-scoped — most notably
`active_model_key`, the globally selected AI model preset.
"""

import aiosqlite
from typing import Optional
from loguru import logger

from src.exceptions.configuration import AdminConfigurationError


_ACTIVE_MODEL_KEY = "active_model_key"


class AppSettingsRepository:
    """Generic key-value repository for admin-managed global settings."""

    def __init__(self, database):
        self._db = database

    async def get(self, key: str) -> Optional[str]:
        """Return the stored string value for `key`, or None if absent."""
        async with aiosqlite.connect(self._db.db_path) as db:
            cursor = await db.execute(
                "SELECT value FROM app_settings WHERE key = ?",
                (key,),
            )
            row = await cursor.fetchone()
            return row[0] if row else None

    async def set(self, key: str, value: str, admin_id: Optional[int]) -> None:
        """UPSERT `key` to `value`, recording `admin_id` as `updated_by`."""
        async with aiosqlite.connect(self._db.db_path) as db:
            await db.execute(
                """
                INSERT INTO app_settings (key, value, updated_by, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_by = excluded.updated_by,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (key, value, admin_id),
            )
            await db.commit()

    async def get_active_model_key(self) -> Optional[str]:
        """Return the globally selected model preset key, or None."""
        return await self.get(_ACTIVE_MODEL_KEY)

    async def set_active_model_key(self, preset_key: str, admin_id: int) -> None:
        """Validate the preset and store it as the active model.

        Raises `AdminConfigurationError` if the preset does not exist or is disabled.
        """
        async with aiosqlite.connect(self._db.db_path) as db:
            cursor = await db.execute(
                "SELECT is_enabled FROM model_presets WHERE key = ?",
                (preset_key,),
            )
            row = await cursor.fetchone()
            if row is None:
                raise AdminConfigurationError(
                    f"Пресет '{preset_key}' не существует"
                )
            if not row[0]:
                raise AdminConfigurationError(
                    f"Пресет '{preset_key}' отключён и не может быть активным"
                )

        await self.set(_ACTIVE_MODEL_KEY, preset_key, admin_id=admin_id)
        logger.info(
            f"active_model_key set to '{preset_key}' by admin {admin_id}"
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_app_settings_repo.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/database/app_settings_repo.py tests/test_app_settings_repo.py tests/conftest.py
git commit -m "feat(db): add AppSettingsRepository with active_model_key helper"
```

---

### Task 4: Guard `ModelPresetRepository` against deleting/disabling active preset

**Files:**
- Modify: `src/database/model_preset_repo.py`
- Create: `tests/test_model_preset_active_guards.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_model_preset_active_guards.py`:

```python
"""Guards: cannot delete or disable the active preset."""
import pytest
from src.exceptions.configuration import ActivePresetDeletionError


async def _seed_preset(repo, key="active", enabled=True):
    await repo.upsert(key=key, name=key, model="m", base_url="u")
    if not enabled:
        await repo.update_field(key, "is_enabled", 0)


@pytest.mark.asyncio
async def test_delete_active_preset_raises(test_db, app_settings_repo):
    from src.database.model_preset_repo import ModelPresetRepository
    repo = ModelPresetRepository(test_db)
    await _seed_preset(repo, key="active")
    await app_settings_repo.set_active_model_key("active", admin_id=42)

    with pytest.raises(ActivePresetDeletionError):
        await repo.delete("active")


@pytest.mark.asyncio
async def test_delete_inactive_preset_succeeds(test_db, app_settings_repo):
    from src.database.model_preset_repo import ModelPresetRepository
    repo = ModelPresetRepository(test_db)
    await _seed_preset(repo, key="active")
    await _seed_preset(repo, key="other")
    await app_settings_repo.set_active_model_key("active", admin_id=42)

    result = await repo.delete("other")
    assert result is True


@pytest.mark.asyncio
async def test_disable_active_preset_raises(test_db, app_settings_repo):
    from src.database.model_preset_repo import ModelPresetRepository
    repo = ModelPresetRepository(test_db)
    await _seed_preset(repo, key="active")
    await app_settings_repo.set_active_model_key("active", admin_id=42)

    with pytest.raises(ActivePresetDeletionError):
        await repo.update_field("active", "is_enabled", 0)


@pytest.mark.asyncio
async def test_update_other_fields_on_active_preset_allowed(test_db, app_settings_repo):
    """update_field setting non-is_enabled fields (or is_enabled=1) on the active preset is fine."""
    from src.database.model_preset_repo import ModelPresetRepository
    repo = ModelPresetRepository(test_db)
    await _seed_preset(repo, key="active")
    await app_settings_repo.set_active_model_key("active", admin_id=42)

    # Setting other fields is OK
    ok = await repo.update_field("active", "name", "Renamed")
    assert ok is True

    # Setting is_enabled to 1 (already 1) is OK
    ok = await repo.update_field("active", "is_enabled", 1)
    assert ok is True
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `pytest tests/test_model_preset_active_guards.py -v`
Expected: 3 of 4 tests FAIL — the repository currently allows the operation.

- [ ] **Step 3: Implement the guards**

In `src/database/model_preset_repo.py`:

1. At top of file, add the import (near the other imports):

```python
from src.exceptions.configuration import ActivePresetDeletionError
```

2. Replace the `delete` method (currently lines 113-121) with:

```python
    async def delete(self, key: str) -> bool:
        """Delete a preset by key. Returns True if a row was deleted.

        Raises `ActivePresetDeletionError` if `key` is the globally active model.
        """
        await self._check_not_active(key, operation="удалить")
        async with aiosqlite.connect(self._db.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM model_presets WHERE key = ?",
                (key,),
            )
            await db.commit()
            return cursor.rowcount > 0
```

3. Replace the `update_field` method (currently lines 93-111) with:

```python
    async def update_field(self, key: str, field: str, value: Any) -> bool:
        """Update a single field for a preset identified by key.

        Returns True when a row was affected.
        Raises ValueError if the field name is not in the whitelist.
        Raises ActivePresetDeletionError when disabling the active preset.
        """
        if field not in _ALLOWED_FIELDS:
            raise ValueError(
                f"Field '{field}' is not allowed. "
                f"Allowed fields: {', '.join(sorted(_ALLOWED_FIELDS))}"
            )

        # Block disabling the active preset
        if field == "is_enabled" and int(value) == 0:
            await self._check_not_active(key, operation="отключить")

        async with aiosqlite.connect(self._db.db_path) as db:
            cursor = await db.execute(
                f"UPDATE model_presets SET {field} = ? WHERE key = ?",
                (value, key),
            )
            await db.commit()
            return cursor.rowcount > 0
```

4. Add this private helper inside the class (place it before `sync_from_config`):

```python
    async def _check_not_active(self, key: str, operation: str) -> None:
        """Raise ActivePresetDeletionError if `key` is the globally active preset.

        `operation` is interpolated into the error message ("удалить" / "отключить").
        """
        from src.database.app_settings_repo import AppSettingsRepository
        app_settings_repo = AppSettingsRepository(self._db)
        active_key = await app_settings_repo.get_active_model_key()
        if active_key == key:
            raise ActivePresetDeletionError(
                f"Нельзя {operation} активный пресет '{key}'. "
                "Сначала выберите другой пресет в /settings → Модель ИИ."
            )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_model_preset_active_guards.py -v`
Expected: 4 passed.

- [ ] **Step 5: Run the full test suite**

Run: `pytest tests/ -x -q`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/database/model_preset_repo.py tests/test_model_preset_active_guards.py
git commit -m "feat(db): guard active preset against delete/disable"
```

---

## Stage B — Provider simplification

### Task 5: Simplify `OpenAIProvider` — accept `preset` directly, add `invalidate_cache_for`

**Files:**
- Modify: `src/llm/providers/openai_provider.py`
- Create: `tests/test_openai_provider.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_openai_provider.py`:

```python
"""Tests for OpenAIProvider preset handling and cache invalidation."""
import pytest
from unittest.mock import MagicMock


def test_invalidate_cache_for_removes_matching_entry():
    """invalidate_cache_for(base_url, api_key_hash) removes that cached client."""
    from src.llm.providers.openai_provider import OpenAIProvider

    p = OpenAIProvider.__new__(OpenAIProvider)
    p.default_client = None
    p._client_cache = {
        ("https://api.openai.com/v1", 12345): MagicMock(),
        ("https://other.com/v1", 67890): MagicMock(),
    }
    p._http_clients = []

    p.invalidate_cache_for(base_url="https://api.openai.com/v1", api_key_hash=12345)
    assert ("https://api.openai.com/v1", 12345) not in p._client_cache
    assert ("https://other.com/v1", 67890) in p._client_cache


def test_invalidate_cache_for_missing_entry_is_noop():
    """No-op when there's nothing to invalidate."""
    from src.llm.providers.openai_provider import OpenAIProvider

    p = OpenAIProvider.__new__(OpenAIProvider)
    p.default_client = None
    p._client_cache = {}
    p._http_clients = []

    p.invalidate_cache_for(base_url="nope", api_key_hash=None)  # must not raise
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `pytest tests/test_openai_provider.py -v`
Expected: tests FAIL — `invalidate_cache_for` does not exist.

- [ ] **Step 3: Implement the cache-invalidation method**

In `src/llm/providers/openai_provider.py`, add this method to `OpenAIProvider` (place after `close`, before `is_available`):

```python
    def invalidate_cache_for(self, base_url: str, api_key_hash: Optional[int]) -> None:
        """Remove the cached OpenAI client for the given (base_url, api_key_hash) tuple.

        Used after a preset is updated so the next call rebuilds the client with the
        new credentials.
        """
        cache_key = (base_url, api_key_hash)
        client = self._client_cache.pop(cache_key, None)
        if client is not None:
            logger.info(f"Invalidated OpenAI client cache for {base_url}")
```

- [ ] **Step 4: Refactor `generate_protocol` to accept `preset` directly**

In `src/llm/providers/openai_provider.py`, replace the model-resolution block at lines 102-123:

```python
        selected_model = settings.openai_model
        openai_model_key = kwargs.get('openai_model_key')
        preset_dict = None

        if openai_model_key:
            try:
                from src.database.model_preset_repo import ModelPresetRepository
                from src.database import db
                repo = ModelPresetRepository(db)
                preset_dict = await repo.get_by_key(openai_model_key)

                if preset_dict:
                    selected_model = preset_dict['model']
                    logger.info(f"Используется модель из БД: {selected_model} (ключ: {openai_model_key})")
                else:
                    preset = next((p for p in settings.openai_models if p.key == openai_model_key), None)
                    if preset:
                        selected_model = preset.model
                        preset_dict = {'base_url': preset.base_url, 'api_key': None}
                        logger.info(f"Используется модель из конфига: {selected_model} (ключ: {openai_model_key})")
            except Exception as e:
                logger.warning(f"Не удалось определить модель по ключу {openai_model_key}: {e}")
```

with:

```python
        preset_dict = kwargs.get('preset')
        if preset_dict and preset_dict.get('model'):
            selected_model = preset_dict['model']
            logger.info(
                f"Используется модель: {selected_model} "
                f"(ключ: {preset_dict.get('key')})"
            )
        else:
            selected_model = settings.openai_model
```

- [ ] **Step 5: Run the tests**

Run: `pytest tests/test_openai_provider.py -v`
Expected: Both tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/llm/providers/openai_provider.py tests/test_openai_provider.py
git commit -m "refactor(openai): accept preset directly, add cache invalidation"
```

---

### Task 6: Strip Anthropic/Yandex from `LLMManager`; new `generate_protocol(preset=…)` signature

**Files:**
- Modify: `src/llm/manager.py`
- Modify: `src/llm/providers/__init__.py`
- Modify: `tests/test_llm_manager.py`

- [ ] **Step 1: Update the failing test**

Replace `tests/test_llm_manager.py` content with:

```python
"""Tests for LLMManager (single-provider, preset-based)."""
import importlib.util
import os
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock

_manager_path = os.path.join(os.path.dirname(__file__), "..", "src", "llm", "manager.py")

# Pre-register a fake openai_provider so manager.py import does not need real OpenAI deps
fake = type(sys)("fake")
fake.OpenAIProvider = MagicMock
sys.modules.setdefault("src.llm.providers.openai_provider", fake)

_spec = importlib.util.spec_from_file_location("llm_manager", _manager_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
LLMManager = _mod.LLMManager


@pytest.mark.asyncio
async def test_manager_passes_preset_to_provider():
    manager = LLMManager.__new__(LLMManager)
    mock_provider = MagicMock()
    mock_provider.is_available.return_value = True
    mock_provider.generate_protocol = AsyncMock(return_value={"summary": "test"})
    manager.providers = {"openai": mock_provider}

    preset = {"key": "k1", "model": "gpt-4o-mini", "base_url": "u", "api_key": "a"}
    result = await manager.generate_protocol(
        preset=preset,
        transcription="text",
        template_variables={"summary": "S"},
    )
    assert result == {"summary": "test"}
    _, kwargs = mock_provider.generate_protocol.call_args
    assert kwargs.get("preset") == preset


@pytest.mark.asyncio
async def test_manager_raises_when_openai_unavailable():
    manager = LLMManager.__new__(LLMManager)
    mock_provider = MagicMock()
    mock_provider.is_available.return_value = False
    manager.providers = {"openai": mock_provider}

    with pytest.raises(ValueError):
        await manager.generate_protocol(
            preset={"key": "k", "model": "m"},
            transcription="",
            template_variables={},
        )
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `pytest tests/test_llm_manager.py -v`
Expected: tests FAIL — current `generate_protocol` expects `provider_name`, not `preset`.

- [ ] **Step 3: Rewrite `src/llm/manager.py`**

Replace the entire content with:

```python
"""LLM provider manager — single-provider (OpenAI-compatible)."""
from typing import Dict, Any, Optional
from loguru import logger

from src.llm.providers.openai_provider import OpenAIProvider


class LLMManager:
    """Manager that delegates to a single OpenAI-compatible provider."""

    def __init__(self):
        self.providers = {"openai": OpenAIProvider()}

    async def generate_protocol(
        self,
        preset: Dict[str, Any],
        transcription: str,
        template_variables: Dict[str, str],
        diarization_data: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Generate a protocol using the given preset.

        `preset` is a fully resolved row from `model_presets` (dict with
        `key`, `model`, `base_url`, `api_key`, `name`). The provider receives it
        via `kwargs['preset']`.
        """
        provider = self.providers["openai"]
        if not provider.is_available():
            raise ValueError("OpenAI провайдер недоступен")

        return await provider.generate_protocol(
            transcription,
            template_variables,
            diarization_data,
            preset=preset,
            **kwargs,
        )


async def generate_protocol(
    manager: 'LLMManager',
    preset: Dict[str, Any],
    transcription: str,
    template_variables: Dict[str, str],
    diarization_data: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Module-level convenience wrapper used by older call sites."""
    return await manager.generate_protocol(
        preset=preset,
        transcription=transcription,
        template_variables=template_variables,
        diarization_data=diarization_data,
        **kwargs,
    )
```

- [ ] **Step 4: Drop Anthropic/Yandex from provider package init**

Replace `src/llm/providers/__init__.py` content with:

```python
"""LLM provider implementations."""
from .openai_provider import OpenAIProvider

__all__ = ["OpenAIProvider"]
```

- [ ] **Step 5: Run the tests**

Run: `pytest tests/test_llm_manager.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add src/llm/manager.py src/llm/providers/__init__.py tests/test_llm_manager.py
git commit -m "refactor(llm): drop multi-provider, use preset-based generate_protocol"
```

---

### Task 7: Simplify `EnhancedLLMService` — single provider, preset-based API

**Files:**
- Modify: `src/services/enhanced_llm_service.py`
- Create: `tests/test_enhanced_llm_service.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_enhanced_llm_service.py`:

```python
"""Tests for EnhancedLLMService — preset-based API."""
import pytest
from unittest.mock import MagicMock, AsyncMock


@pytest.mark.asyncio
async def test_generate_protocol_with_preset_delegates(monkeypatch):
    """The new entry point calls llm_manager.generate_protocol with the preset."""
    from src.services import enhanced_llm_service as ells_module

    # Mock the manager singleton inside the service
    fake_manager = MagicMock()
    fake_manager.generate_protocol = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(ells_module, "llm_manager", fake_manager)

    # Patch fallback_manager creator with a stub that just runs the primary handler
    class StubFallback:
        def __init__(self):
            self.primary = None
            self.last_execution = {"mode": "primary"}

        def set_primary(self, handler):
            self.primary = handler

        async def execute(self, *args, **kwargs):
            return await self.primary(*args, **kwargs)

        def get_stats(self):
            return {}

        def clear_cache(self):
            pass

    monkeypatch.setattr(ells_module, "create_llm_fallback_manager", lambda: StubFallback())

    svc = ells_module.EnhancedLLMService()
    preset = {"key": "k", "model": "gpt-4o-mini", "base_url": "u", "api_key": "a"}
    result = await svc.generate_protocol_with_preset(
        preset=preset,
        transcription="hello",
        template_variables={},
        diarization_data=None,
    )
    assert result == {"ok": True}
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `pytest tests/test_enhanced_llm_service.py -v`
Expected: FAIL — `generate_protocol_with_preset` does not exist.

- [ ] **Step 3: Rewrite `src/services/enhanced_llm_service.py`**

Replace the entire content with:

```python
"""Enhanced LLM service — single-provider (OpenAI) with reliability stack."""

from typing import Dict, Any, Optional
from loguru import logger

from src.exceptions.processing import LLMError
from src.reliability import (
    RetryManager, LLM_RETRY_CONFIG,
    CircuitBreaker, CircuitBreakerConfig, DEFAULT_CIRCUIT_BREAKER_CONFIG,
    RateLimiter, global_rate_limiter, OPENAI_API_LIMIT,
    FallbackManager, create_llm_fallback_manager,
)
from config import settings
from llm_providers import llm_manager


class EnhancedLLMService:
    """LLM service with retry/circuit-breaker/rate-limit + cached-fallback safety net."""

    def __init__(self):
        self.llm_manager = llm_manager

        cb_config = CircuitBreakerConfig(
            failure_threshold=DEFAULT_CIRCUIT_BREAKER_CONFIG.failure_threshold,
            recovery_timeout=DEFAULT_CIRCUIT_BREAKER_CONFIG.recovery_timeout,
            success_threshold=DEFAULT_CIRCUIT_BREAKER_CONFIG.success_threshold,
            timeout=settings.llm_timeout_seconds,
        )
        self.retry_manager = RetryManager(LLM_RETRY_CONFIG)
        self.circuit_breaker = CircuitBreaker("openai_llm", cb_config)
        self.rate_limiter = global_rate_limiter.get_or_create(
            "openai_api", OPENAI_API_LIMIT
        )
        self.fallback_manager = create_llm_fallback_manager()
        self.fallback_manager.set_primary(self._generate_protocol_primary)

    async def _generate_protocol_primary(
        self,
        preset: Dict[str, Any],
        transcription: str,
        template_variables: Dict[str, str],
        diarization_data: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Primary path: rate-limit -> circuit-breaker -> retry -> manager."""
        await self.rate_limiter.acquire()

        async def protected_call():
            return await self.retry_manager.execute_with_retry(
                self.llm_manager.generate_protocol,
                preset=preset,
                transcription=transcription,
                template_variables=template_variables,
                diarization_data=diarization_data,
                **kwargs,
            )

        return await self.circuit_breaker.call(protected_call)

    async def generate_protocol_with_preset(
        self,
        preset: Dict[str, Any],
        transcription: str,
        template_variables: Dict[str, str],
        diarization_data: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Run LLM with cached fallback as a safety net."""
        cache_key = f"openai_{hash(transcription[:100])}"
        try:
            result = await self.fallback_manager.execute(
                preset,
                transcription,
                template_variables,
                diarization_data,
                cache_key=cache_key,
                **kwargs,
            )
            exec_info = getattr(self.fallback_manager, 'last_execution', {})
            if exec_info.get('mode') == 'fallback':
                logger.info(
                    f"Возвращён результат через fallback: "
                    f"{exec_info.get('fallback_name')}"
                )
            elif exec_info.get('mode') == 'cache':
                logger.info("Возвращён результат из кеша fallback-менеджера")
            return result
        except Exception as e:
            logger.error(f"LLM не сработал: {e}")
            raise LLMError(str(e), "openai", preset.get("model"))

    def get_reliability_stats(self) -> Dict[str, Any]:
        return {
            "fallback_manager": self.fallback_manager.get_stats(),
            "circuit_breaker": self.circuit_breaker.get_stats(),
            "rate_limiter": self.rate_limiter.get_stats(),
        }

    async def reset_reliability_components(self):
        await self.circuit_breaker.reset()
        self.fallback_manager.clear_cache()
        logger.info("Сброшены компоненты надежности LLM")
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/test_enhanced_llm_service.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/services/enhanced_llm_service.py tests/test_enhanced_llm_service.py
git commit -m "refactor(llm-service): single-provider preset-based API"
```

---

## Stage C — Wire processing-time resolver

### Task 8: Resolve active model in `LLMGenerationService`

**Files:**
- Modify: `src/services/processing/llm_generation.py`
- Create: `tests/test_active_model_resolver.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_active_model_resolver.py`:

```python
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
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `pytest tests/test_active_model_resolver.py -v`
Expected: tests FAIL — `resolve_active_preset` does not exist.

- [ ] **Step 3: Add the resolver and switch the model-resolution path**

In `src/services/processing/llm_generation.py`:

1. At the top, after the existing imports (after `from .protocol_formatter import ProtocolFormatter`), add:

```python
from src.exceptions.configuration import AdminConfigurationError
```

2. Add the resolver function at module level (above the `LLMGenerationService` class, after the imports):

```python
async def resolve_active_preset(app_settings_repo, preset_repo) -> Dict[str, Any]:
    """Return the currently active model preset.

    Raises `AdminConfigurationError` when no key is set or the referenced preset
    is missing/disabled.
    """
    active_key = await app_settings_repo.get_active_model_key()
    if not active_key:
        raise AdminConfigurationError(
            "Активная модель не настроена администратором"
        )
    preset = await preset_repo.get_by_key(active_key)
    if not preset or not preset.get("is_enabled"):
        raise AdminConfigurationError(
            f"Активная модель '{active_key}' недоступна"
        )
    return preset
```

3. Replace the per-user `openai_model_key` lookup (currently lines 71-81) inside `optimized_llm_generation`:

```python
            # Определяем ключ пресета модели OpenAI
            openai_model_key = None
            try:
                user = await self._user_service.get_user_by_telegram_id(request.user_id)
                if user and request.llm_provider == 'openai':
                    openai_model_key = getattr(user, 'preferred_openai_model_key', None)
            except Exception:
                openai_model_key = None

            # Определяем название используемой модели
            llm_model_name = await self.get_model_display_name(request.llm_provider, openai_model_key)  # noqa: F841
```

with:

```python
            # Резолвим активную модель (глобальная админ-настройка)
            from src.database.app_settings_repo import AppSettingsRepository
            from src.database.model_preset_repo import ModelPresetRepository
            from database import db as app_db

            app_settings_repo = AppSettingsRepository(app_db)
            preset_repo = ModelPresetRepository(app_db)
            active_preset = await resolve_active_preset(app_settings_repo, preset_repo)
            llm_model_name = active_preset["name"]  # noqa: F841
```

4. In the consolidated generation branch (the call to module-level `generate_protocol` around lines 140-158), replace the invocation to use the new preset-based signature:

Change:
```python
                llm_result_data = await generate_protocol(
                    manager=llm_manager,
                    provider_name=request.llm_provider,
                    transcription=transcription_text,
                    template_variables=template_variables,
                    diarization_data=transcription_result.diarization,
                    diarization_analysis=diarization_analysis,
                    participants_list=participants_list,
                    meeting_metadata=meeting_metadata,
                    openai_model_key=openai_model_key,
                    speaker_mapping=request.speaker_mapping,
                    meeting_type=meeting_type,
                    meeting_topic=request.meeting_topic,
                    meeting_date=request.meeting_date,
                    meeting_time=request.meeting_time,
                    participants=request.participants_list,
                    meeting_agenda=request.meeting_agenda,
                    project_list=request.project_list,
                )
```

to:

```python
                llm_result_data = await generate_protocol(
                    manager=llm_manager,
                    preset=active_preset,
                    transcription=transcription_text,
                    template_variables=template_variables,
                    diarization_data=transcription_result.diarization,
                    diarization_analysis=diarization_analysis,
                    participants_list=participants_list,
                    meeting_metadata=meeting_metadata,
                    speaker_mapping=request.speaker_mapping,
                    meeting_type=meeting_type,
                    meeting_topic=request.meeting_topic,
                    meeting_date=request.meeting_date,
                    meeting_time=request.meeting_time,
                    participants=request.participants_list,
                    meeting_agenda=request.meeting_agenda,
                    project_list=request.project_list,
                )
```

5. In the `else` branch (the `task_pool.submit_task(... self.generate_llm_response, ...)` block around lines 164-179), replace the positional `request.llm_provider, openai_model_key` arguments with the single `active_preset`:

```python
                llm_result = await task_pool.submit_task(
                    llm_task_id,
                    self.generate_llm_response,
                    transcription_result,
                    template,
                    template_variables,
                    active_preset,
                    request.speaker_mapping,
                    request.meeting_topic,
                    request.meeting_date,
                    request.meeting_time,
                    request.participants_list,
                    request.meeting_agenda,
                    request.project_list,
                )
```

6. Update `generate_llm_response` (currently lines 354-387) to accept `preset` instead of `llm_provider, openai_model_key`:

```python
    async def generate_llm_response(
        self,
        transcription_result,
        template,
        template_variables,
        preset,
        speaker_mapping=None,
        meeting_topic=None,
        meeting_date=None,
        meeting_time=None,
        participants=None,
        meeting_agenda=None,
        project_list=None,
    ):
        """Генерация ответа LLM с постобработкой."""
        llm_result = await self._llm_service.generate_protocol_with_preset(
            preset=preset,
            transcription=transcription_result.transcription,
            template_variables=template_variables,
            diarization_data=transcription_result.diarization
            if hasattr(transcription_result, 'diarization')
            else None,
            speaker_mapping=speaker_mapping,
            meeting_topic=meeting_topic,
            meeting_date=meeting_date,
            meeting_time=meeting_time,
            participants=participants,
            meeting_agenda=meeting_agenda,
            project_list=project_list,
        )

        return self.post_process_llm_result(llm_result)
```

7. Simplify `get_model_display_name` (currently lines 322-352) to take an optional preset:

```python
    async def get_model_display_name(self, preset: Optional[Dict[str, Any]] = None) -> str:
        """Return a human-readable name for the active model preset."""
        if preset:
            return preset.get("name") or preset.get("model") or "GPT"
        return settings.openai_model or "GPT-4o"
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_active_model_resolver.py -v`
Expected: 3 passed.

- [ ] **Step 5: Run the full suite**

Run: `pytest tests/ -x -q`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/services/processing/llm_generation.py tests/test_active_model_resolver.py
git commit -m "feat(processing): resolve active model preset from app_settings"
```

---

### Task 9: Update `ProcessingService` to use the new model display name resolver

**Files:**
- Modify: `src/services/processing/processing_service.py`

- [ ] **Step 1: Capture baseline**

Run: `pytest tests/ -x -q`
Expected: green.

- [ ] **Step 2: Replace the two `openai_model_key` lookup blocks**

In `src/services/processing/processing_service.py`:

1. Locate the two blocks (around lines 402-407 and 744-748) that look like:

```python
            openai_model_key = None
            if request.llm_provider == 'openai':
                openai_model_key = getattr(user, 'preferred_openai_model_key', None)
            llm_model_display_name = await self._get_model_display_name(
                request.llm_provider, openai_model_key
            )
```

Replace each with:

```python
            from src.database.app_settings_repo import AppSettingsRepository
            from src.database.model_preset_repo import ModelPresetRepository
            from database import db as app_db
            from src.services.processing.llm_generation import resolve_active_preset

            try:
                active_preset = await resolve_active_preset(
                    AppSettingsRepository(app_db),
                    ModelPresetRepository(app_db),
                )
                llm_model_display_name = active_preset.get("name") or active_preset.get("model")
            except Exception:
                llm_model_display_name = "?"
```

2. Find the private helper `_get_model_display_name` (currently lines 111-112):

```python
    async def _get_model_display_name(self, provider, openai_model_key=None):
        return await self.llm_gen.get_model_display_name(provider, openai_model_key)
```

Replace with:

```python
    async def _get_model_display_name(self, preset=None):
        return await self.llm_gen.get_model_display_name(preset)
```

Search for any remaining callers of `_get_model_display_name` in this file — there should be none after the two blocks above are rewritten. If any remain, update them to pass `preset` instead.

- [ ] **Step 3: Run the full suite**

Run: `pytest tests/ -x -q`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/services/processing/processing_service.py
git commit -m "refactor(processing): use active preset for model display name"
```

---

## Stage D — UI surface

### Task 10: `create_settings_menu(is_admin)`

**Files:**
- Modify: `src/ux/quick_actions.py`
- Create: `tests/test_settings_menu.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_settings_menu.py`:

```python
"""Tests for the is_admin-aware settings menu."""
from src.ux.quick_actions import QuickActionsUI


def _callback_data_set(keyboard):
    return {
        btn.callback_data
        for row in keyboard.inline_keyboard
        for btn in row
        if btn.callback_data
    }


def test_admin_sees_active_model_button():
    keyboard = QuickActionsUI.create_settings_menu(is_admin=True)
    data = _callback_data_set(keyboard)
    assert "settings_active_model" in data
    # Old per-user buttons are gone
    assert "settings_preferred_llm" not in data
    assert "settings_openai_model" not in data


def test_non_admin_does_not_see_active_model_button():
    keyboard = QuickActionsUI.create_settings_menu(is_admin=False)
    data = _callback_data_set(keyboard)
    assert "settings_active_model" not in data
    assert "settings_preferred_llm" not in data
    assert "settings_openai_model" not in data


def test_non_admin_still_sees_other_settings():
    keyboard = QuickActionsUI.create_settings_menu(is_admin=False)
    data = _callback_data_set(keyboard)
    assert "settings_protocol_output" in data
    assert "settings_default_template" in data
    assert "settings_stats" in data
    assert "settings_reset" in data
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `pytest tests/test_settings_menu.py -v`
Expected: FAIL — `create_settings_menu()` does not accept `is_admin`.

- [ ] **Step 3: Modify `create_settings_menu`**

In `src/ux/quick_actions.py`, replace the existing `create_settings_menu` (lines 125-167) with:

```python
    @staticmethod
    def create_settings_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
        """Меню настроек. Админ дополнительно видит выбор активной модели ИИ."""
        buttons = []

        if is_admin:
            buttons.append([
                InlineKeyboardButton(
                    text="🤖 Модель ИИ",
                    callback_data="settings_active_model",
                )
            ])

        buttons.extend([
            [
                InlineKeyboardButton(
                    text="📤 Вывод протокола",
                    callback_data="settings_protocol_output",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📝 Шаблон по умолчанию",
                    callback_data="settings_default_template",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Статистика",
                    callback_data="settings_stats",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Сбросить настройки",
                    callback_data="settings_reset",
                )
            ],
        ])

        return InlineKeyboardMarkup(inline_keyboard=buttons)
```

- [ ] **Step 4: Update the call sites**

Run: `grep -rn "create_settings_menu" src/`
Expected callers (other than the definition in `quick_actions.py`):
- `src/handlers/callbacks/settings_callbacks.py:321` (inside `back_to_settings_callback`)

For each caller, pass `is_admin=_is_admin(<telegram_id>)`. Concretely, in `src/handlers/callbacks/settings_callbacks.py`, replace:

```python
            keyboard = QuickActionsUI.create_settings_menu()
```

with:

```python
            from src.utils.admin_utils import is_admin as _is_admin
            keyboard = QuickActionsUI.create_settings_menu(
                is_admin=_is_admin(callback.from_user.id)
            )
```

- [ ] **Step 5: Run the tests**

Run: `pytest tests/test_settings_menu.py tests/ -x -q`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/ux/quick_actions.py src/handlers/callbacks/settings_callbacks.py tests/test_settings_menu.py
git commit -m "feat(ui): admin-only Модель ИИ button in settings menu"
```

---

### Task 11: Add `settings_active_model` callback handler

**Files:**
- Modify: `src/handlers/callbacks/settings_callbacks.py`

- [ ] **Step 1: Capture baseline**

Run: `pytest tests/ -x -q`
Expected: green.

- [ ] **Step 2: Add the new callback handler**

In `src/handlers/callbacks/settings_callbacks.py`, inside `setup_settings_callbacks` (after `back_to_settings_callback`, before the closing `return router`), add:

```python
    @router.callback_query(F.data == "settings_active_model")
    async def settings_active_model_callback(callback: CallbackQuery):
        """Show the active-model picker (admin only)."""
        from src.utils.admin_utils import is_admin
        if not is_admin(callback.from_user.id):
            logger.warning(
                f"Non-admin {callback.from_user.id} attempted to open settings_active_model"
            )
            await callback.answer(
                "❌ Доступно только администратору", show_alert=True
            )
            return

        try:
            from src.database.model_preset_repo import ModelPresetRepository
            from src.database.app_settings_repo import AppSettingsRepository
            from database import db as app_db

            preset_repo = ModelPresetRepository(app_db)
            app_settings_repo = AppSettingsRepository(app_db)

            presets = await preset_repo.get_enabled()
            if not presets:
                await safe_edit_text(
                    callback.message,
                    "❌ Нет доступных моделей.\n\n"
                    "Используйте /add_model чтобы добавить модель.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(
                            text="⬅️ Назад к настройкам",
                            callback_data="back_to_settings",
                        )]
                    ]),
                )
                await callback.answer()
                return

            active_key = await app_settings_repo.get_active_model_key()
            rows = []
            for p in presets:
                marker = "✅ " if p["key"] == active_key else ""
                rows.append([InlineKeyboardButton(
                    text=f"{marker}{p['name']}",
                    callback_data=f"set_active_model_{p['key']}",
                )])
            rows.append([InlineKeyboardButton(
                text="⬅️ Назад к настройкам",
                callback_data="back_to_settings",
            )])

            await safe_edit_text(
                callback.message,
                "🤖 **Модель ИИ**\n\n"
                "Выберите модель, которая будет использоваться ботом:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
                parse_mode="Markdown",
            )
            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка в settings_active_model_callback: {e}")
            await callback.answer("❌ Не удалось загрузить список моделей")
```

- [ ] **Step 3: Smoke-test imports**

Run: `python -c "from src.handlers.callbacks.settings_callbacks import setup_settings_callbacks; print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add src/handlers/callbacks/settings_callbacks.py
git commit -m "feat(ui): add settings_active_model admin-only handler"
```

---

### Task 12: Add `set_active_model_<key>` callback (with admin guard + global write)

**Files:**
- Modify: `src/handlers/callbacks/settings_callbacks.py`

- [ ] **Step 1: Add the handler**

In `src/handlers/callbacks/settings_callbacks.py`, immediately after `settings_active_model_callback`, add:

```python
    @router.callback_query(F.data.startswith("set_active_model_"))
    async def set_active_model_callback(callback: CallbackQuery):
        """Apply admin's choice of active model (admin only)."""
        from src.utils.admin_utils import is_admin
        if not is_admin(callback.from_user.id):
            logger.warning(
                f"Non-admin {callback.from_user.id} attempted set_active_model"
            )
            await callback.answer(
                "❌ Доступно только администратору", show_alert=True
            )
            return

        try:
            preset_key = callback.data.replace("set_active_model_", "", 1)

            from src.database.model_preset_repo import ModelPresetRepository
            from src.database.app_settings_repo import AppSettingsRepository
            from src.exceptions.configuration import AdminConfigurationError
            from database import db as app_db

            app_settings_repo = AppSettingsRepository(app_db)
            preset_repo = ModelPresetRepository(app_db)

            try:
                await app_settings_repo.set_active_model_key(
                    preset_key, admin_id=callback.from_user.id
                )
            except AdminConfigurationError as e:
                await callback.answer(f"❌ {e.message}", show_alert=True)
                return

            preset = await preset_repo.get_by_key(preset_key)
            model_name = preset["name"] if preset else preset_key

            await safe_edit_text(
                callback.message,
                f"✅ Активная модель: **{model_name}**\n\n"
                "Бот будет использовать эту модель для всех обработок.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="⬅️ Назад к настройкам",
                        callback_data="back_to_settings",
                    )]
                ]),
                parse_mode="Markdown",
            )
            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка в set_active_model_callback: {e}")
            await callback.answer("❌ Не удалось сохранить выбор модели")
```

- [ ] **Step 2: Smoke-test imports**

Run: `python -c "from src.handlers.callbacks.settings_callbacks import setup_settings_callbacks; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/handlers/callbacks/settings_callbacks.py
git commit -m "feat(ui): add set_active_model handler with admin guard"
```

---

### Task 13: Remove old per-user model/provider callbacks

**Files:**
- Modify: `src/handlers/callbacks/settings_callbacks.py`

- [ ] **Step 1: Capture baseline**

Run: `pytest tests/ -x -q`
Expected: green.

- [ ] **Step 2: Delete the obsolete handlers**

In `src/handlers/callbacks/settings_callbacks.py`, delete the following whole handler functions inside `setup_settings_callbacks`:

- `settings_preferred_llm_callback` (currently around lines 18-50)
- `settings_openai_model_callback` (currently around lines 52-89)
- `set_openai_model_callback` (currently around lines 91-123)
- `reset_openai_model_preference_callback` (currently around lines 125-140)

- [ ] **Step 3: Clean up `settings_reset_callback`**

In the same file, in `settings_reset_callback`, delete this line:

```python
            await user_service.update_user_llm_preference(callback.from_user.id, None)
```

(That method is being deleted in Task 20; leaving the call would crash.)

Also remove from the success message:

```
                "• Предпочтения ИИ сброшены\n"
```

- [ ] **Step 4: Verify imports still work**

Run: `python -c "from src.handlers.callbacks.settings_callbacks import setup_settings_callbacks; print('ok')"`
Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
git add src/handlers/callbacks/settings_callbacks.py
git commit -m "refactor(ui): remove obsolete per-user model/provider callbacks"
```

---

### Task 14: Delete `llm_callbacks.py` and stop registering it

**Files:**
- Delete: `src/handlers/callbacks/llm_callbacks.py`
- Modify: `src/handlers/callbacks/__init__.py`
- Modify: `src/bot.py`

- [ ] **Step 1: Find registrations**

Run: `grep -rn "setup_llm_callbacks\|llm_callbacks" src/ main.py`
Expected: matches in `src/handlers/callbacks/__init__.py` and possibly `src/bot.py` or `src/handlers/__init__.py`.

- [ ] **Step 2: Remove imports and registrations**

Open `src/handlers/callbacks/__init__.py`. Find every line that imports `setup_llm_callbacks` or creates the LLM router and delete them. Update the package `__all__` accordingly.

Open `src/bot.py`. Find any reference to `setup_llm_callbacks` or the LLM-callbacks router and delete it.

If `setup_callback_handlers` (in `src/handlers/callbacks/__init__.py`) currently composes routers including the LLM one, also remove the LLM addition there.

Also note: the helper `_show_llm_selection` lives in `llm_callbacks.py`. Search for callers:

Run: `grep -rn "_show_llm_selection\b" src/`

Any caller must be updated to use the new selection-free flow (`_show_llm_selection_for_file` from `message_handlers.py`, which Task 16 already simplifies to "go straight to processing"). Replace any `_show_llm_selection(...)` call site with an inline equivalent that sets `state.update_data(llm_provider='openai')` and proceeds to processing.

- [ ] **Step 3: Delete the file**

Run: `git rm src/handlers/callbacks/llm_callbacks.py`

- [ ] **Step 4: Smoke-test**

Run: `python -c "from src.bot import main_enhanced; print('imports ok')"`
Expected: `imports ok` (no `ImportError` for `setup_llm_callbacks`).

- [ ] **Step 5: Run the full suite**

Run: `pytest tests/ -x -q`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add -A src/handlers/callbacks/ src/bot.py
git commit -m "refactor(ui): drop llm_callbacks (per-user LLM selection removed)"
```

---

### Task 15: Update `/start` and `/settings` text

**Files:**
- Modify: `src/handlers/command_handlers.py`

- [ ] **Step 1: Capture baseline**

Run: `pytest tests/ -x -q`
Expected: green.

- [ ] **Step 2: Rewrite `settings_handler`**

In `src/handlers/command_handlers.py`, replace the entire `settings_handler` function (currently lines 58-125) with:

```python
    @router.message(Command("settings"))
    async def settings_handler(message: Message):
        """Обработчик команды /settings."""
        try:
            from src.utils.admin_utils import is_admin as _is_admin
            from src.ux.quick_actions import QuickActionsUI

            is_admin_user = _is_admin(message.from_user.id)
            keyboard = QuickActionsUI.create_settings_menu(is_admin=is_admin_user)

            text = "⚙️ **Настройки бота**\n\n"

            if is_admin_user:
                # Admins see the currently active model name (read-only line)
                try:
                    from src.database.app_settings_repo import AppSettingsRepository
                    from src.database.model_preset_repo import ModelPresetRepository
                    from database import db as app_db

                    active_key = await AppSettingsRepository(app_db).get_active_model_key()
                    if active_key:
                        preset = await ModelPresetRepository(app_db).get_by_key(active_key)
                        if preset:
                            text += f"Активная модель: {preset['name']}\n\n"
                        else:
                            text += "⚠️ Активная модель не найдена\n\n"
                    else:
                        text += "⚠️ Активная модель не настроена\n\n"
                except Exception as e:
                    logger.warning(f"Не удалось загрузить активную модель: {e}")

            text += "Настройте бота под ваши предпочтения:"

            await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка в settings_handler: {e}")
            await message.answer("❌ Произошла ошибка при загрузке настроек.")
```

- [ ] **Step 3: Keep the existing `setup_command_handlers` signature**

The current signature includes `llm_service: EnhancedLLMService` but the rewritten `settings_handler` no longer uses it. Leave the parameter as-is to avoid touching `bot.py` and the registration call site. It becomes a no-op argument — acceptable.

- [ ] **Step 4: Smoke-test imports**

Run: `python -c "from src.handlers.command_handlers import setup_command_handlers; print('ok')"`
Expected: `ok`.

- [ ] **Step 5: Run the full suite**

Run: `pytest tests/ -x -q`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/handlers/command_handlers.py
git commit -m "refactor(ui): /settings shows active model only for admin"
```

---

### Task 16: Strip LLM selection UI from `message_handlers.py`

**Files:**
- Modify: `src/handlers/message_handlers.py`

- [ ] **Step 1: Capture baseline**

Run: `pytest tests/ -x -q`
Expected: green.

- [ ] **Step 2: Rewrite `_show_llm_selection_for_file`**

In `src/handlers/message_handlers.py`, replace `_show_llm_selection_for_file` (currently lines 157-250) with:

```python
async def _show_llm_selection_for_file(message: Message, state: FSMContext, llm_service, processing_service):
    """LLM selection is gone — go straight to processing.

    Kept under its original name to avoid call-site churn; it now just sets the
    provider to 'openai' in state and starts processing.
    """
    try:
        state_data = await state.get_data()
        template_id = state_data.get('template_id')
        file_id = state_data.get('file_id')
        file_path = state_data.get('file_path')

        if not template_id:
            await message.answer("❌ Ошибка: шаблон не выбран")
            return
        if not file_id and not file_path:
            await message.answer("❌ Ошибка: файл не найден")
            return

        await state.update_data(llm_provider='openai')

        await message.answer(
            "⏳ Начинаю обработку файла...",
            parse_mode="Markdown",
        )
        await _start_file_processing(message, state, processing_service)
    except Exception as e:
        logger.error(f"Ошибка в _show_llm_selection_for_file: {e}")
        await message.answer("❌ Произошла ошибка при запуске обработки.")
```

(The function still accepts `llm_service` for backwards-compatible call sites, but it's unused now.)

- [ ] **Step 3: Smoke-test imports**

Find the setup function name: `grep -n "def setup_" src/handlers/message_handlers.py`

Run: `python -c "from src.handlers.message_handlers import setup_message_handlers; print('ok')"` (or substitute the actual function name found above).
Expected: `ok`.

- [ ] **Step 4: Run the full suite**

Run: `pytest tests/ -x -q`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/handlers/message_handlers.py
git commit -m "refactor(ui): skip LLM selection — proceed straight to processing"
```

---

### Task 17: Enhance `/models` — active marker, "Сделать активной" button, deletion guard

**Files:**
- Modify: `src/handlers/admin_handlers.py`

- [ ] **Step 1: Capture baseline**

Run: `pytest tests/ -x -q`
Expected: green.

- [ ] **Step 2: Add active-key lookup to `_render_models_list`**

In `src/handlers/admin_handlers.py`, replace the entire `_render_models_list` function (currently lines 816-849) with:

```python
    async def _render_models_list(presets):
        """Build text and keyboard for the models list view."""
        from src.database.app_settings_repo import AppSettingsRepository
        from database import db as app_db

        active_key = await AppSettingsRepository(app_db).get_active_model_key()

        if not presets:
            text = "📋 **Список моделей**\n\nМоделей пока нет. Используйте /add\\_model или синхронизируйте из .env."
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="🔄 Синхр. из .env",
                    callback_data="admin_models_sync",
                )],
            ])
            return text, keyboard

        lines = ["📋 **Список моделей**\n"]
        buttons = []
        for p in presets:
            active_marker = " ⭐" if p["key"] == active_key else ""
            if not p.get("is_enabled"):
                icon = "⛔"
            elif p.get("admin_only"):
                icon = "🔒"
            else:
                icon = "✅"
            label = f"{icon} {p['name']}{active_marker}"
            lines.append(label)
            buttons.append([InlineKeyboardButton(
                text=label,
                callback_data=f"admin_model_{p['key']}",
            )])

        buttons.append([InlineKeyboardButton(
            text="🔄 Синхр. из .env",
            callback_data="admin_models_sync",
        )])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        text = "\n".join(lines)
        return text, keyboard
```

- [ ] **Step 3: Add "Сделать активной" button + active flag to detail card**

Replace `_render_model_detail` (currently lines 851-881) with:

```python
    async def _render_model_detail(preset):
        """Build text and keyboard for a single model detail card."""
        from src.database.app_settings_repo import AppSettingsRepository
        from database import db as app_db

        active_key = await AppSettingsRepository(app_db).get_active_model_key()
        is_active = preset["key"] == active_key

        key = preset["key"]
        api_key_status = "✅ задан" if preset.get("api_key") else "❌ не задан"
        enabled_label = "✅ включена" if preset.get("is_enabled") else "⛔ выключена"
        access_label = "🔒 только админы" if preset.get("admin_only") else "👥 все пользователи"
        active_label = "⭐ да" if is_active else "—"

        text = (
            f"🤖 **{preset['name']}**\n\n"
            f"**Key:** `{key}`\n"
            f"**Model ID:** `{preset['model']}`\n"
            f"**Base URL:** `{preset['base_url']}`\n"
            f"**API Key:** {api_key_status}\n"
            f"**Статус:** {enabled_label}\n"
            f"**Доступ:** {access_label}\n"
            f"**Активная:** {active_label}"
        )

        toggle_text = "⛔ Выключить" if preset.get("is_enabled") else "✅ Включить"
        access_text = "👥 Для всех" if preset.get("admin_only") else "🔒 Только админы"

        rows = []
        if not is_active and preset.get("is_enabled"):
            rows.append([InlineKeyboardButton(
                text="▶️ Сделать активной",
                callback_data=f"set_active_model_{key}",
            )])
        rows.extend([
            [
                InlineKeyboardButton(text=toggle_text, callback_data=f"admin_model_toggle_{key}"),
                InlineKeyboardButton(text=access_text, callback_data=f"admin_model_access_{key}"),
            ],
            [
                InlineKeyboardButton(text="🗑 Удалить", callback_data=f"admin_model_delete_{key}"),
                InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_models_list"),
            ],
        ])
        return text, InlineKeyboardMarkup(inline_keyboard=rows)
```

- [ ] **Step 4: Translate `ActivePresetDeletionError` in toggle callback**

In the same file, find `admin_model_toggle_callback` (around line 972). Replace these two lines inside the `try`:

```python
            new_value = 0 if preset.get("is_enabled") else 1
            await repo.update_field(key, "is_enabled", new_value)
```

with:

```python
            from src.exceptions.configuration import ActivePresetDeletionError

            new_value = 0 if preset.get("is_enabled") else 1
            try:
                await repo.update_field(key, "is_enabled", new_value)
            except ActivePresetDeletionError as e:
                await safe_edit_text(callback.message, f"❌ {e.message}")
                return
```

- [ ] **Step 5: Translate `ActivePresetDeletionError` in delete callback**

In `admin_model_delete_callback` (around line 1030), replace:

```python
            deleted = await repo.delete(key)
```

with:

```python
            from src.exceptions.configuration import ActivePresetDeletionError

            try:
                deleted = await repo.delete(key)
            except ActivePresetDeletionError as e:
                await safe_edit_text(callback.message, f"❌ {e.message}")
                return
```

- [ ] **Step 6: Smoke-test**

Run: `python -c "from src.handlers.admin_handlers import setup_admin_handlers; print('ok')"`
Expected: `ok`.

- [ ] **Step 7: Run the full suite**

Run: `pytest tests/ -x -q`
Expected: All tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/handlers/admin_handlers.py
git commit -m "feat(admin): show active marker, add Сделать активной, guard delete"
```

---

## Stage E — Final cleanup

### Task 18: Delete `anthropic_provider.py` and `yandex_provider.py`

**Files:**
- Delete: `src/llm/providers/anthropic_provider.py`
- Delete: `src/llm/providers/yandex_provider.py`

- [ ] **Step 1: Capture baseline**

Run: `pytest tests/ -x -q`
Expected: green.

- [ ] **Step 2: Confirm no remaining imports**

Run: `grep -rn "AnthropicProvider\|YandexGPTProvider\|anthropic_provider\|yandex_provider" src/ tests/ main.py 2>/dev/null | grep -v __pycache__`

Expected: No matches in `src/` outside the two files about to be deleted, and no matches in `tests/`.

If there are unexpected matches (e.g., a stale reference in `enhanced_llm_service.py`), address them now before deleting.

- [ ] **Step 3: Delete the files**

```bash
git rm src/llm/providers/anthropic_provider.py src/llm/providers/yandex_provider.py
```

- [ ] **Step 4: Smoke-test**

Run: `python -c "from src.llm import llm_manager; print('ok', list(llm_manager.providers.keys()))"`
Expected: `ok ['openai']`.

- [ ] **Step 5: Run the full suite**

Run: `pytest tests/ -x -q`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add -A src/llm/providers/
git commit -m "chore(llm): remove Anthropic and Yandex provider implementations"
```

---

### Task 19: Drop Anthropic/Yandex from config, startup check, env_example

**Files:**
- Modify: `src/config.py`
- Modify: `main.py`
- Modify: `env_example`

- [ ] **Step 1: Capture baseline**

Run: `pytest tests/ -x -q`
Expected: green.

- [ ] **Step 2: Remove fields from `src/config.py`**

Delete these lines from `src/config.py` (currently lines 44-49):

```python
    # Anthropic Claude
    anthropic_api_key: Optional[str] = Field(None, description="API ключ Anthropic")

    # Yandex GPT
    yandex_api_key: Optional[str] = Field(None, description="API ключ Yandex GPT")
    yandex_folder_id: Optional[str] = Field(None, description="ID папки Yandex Cloud")
```

- [ ] **Step 3: Update startup check in `main.py`**

In `main.py`, replace lines 63-66:

```python
    # Проверяем наличие хотя бы одного API ключа для LLM
    if not any([settings.openai_api_key, settings.anthropic_api_key, 
                settings.yandex_api_key]):
        logger.warning("Не установлены API ключи для LLM провайдеров")
```

with:

```python
    # Проверяем наличие API ключа OpenAI
    if not settings.openai_api_key:
        logger.warning("OPENAI_API_KEY не установлен")
```

- [ ] **Step 4: Clean `env_example`**

Open `env_example` and remove the three lines for Anthropic/Yandex variables (currently lines 37, 40, 41 — `ANTHROPIC_API_KEY`, `YANDEX_API_KEY`, `YANDEX_FOLDER_ID`). Also remove any nearby comment headers that explicitly reference those providers.

- [ ] **Step 5: Smoke-test config loads**

Run: `python -c "from src.config import settings; print('config ok')"`
Expected: `config ok` (no `ValidationError`).

- [ ] **Step 6: Run the full suite**

Run: `pytest tests/ -x -q`
Expected: All tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/config.py main.py env_example
git commit -m "chore: remove Anthropic and Yandex config fields"
```

---

### Task 20: Remove unused user-preference methods

**Files:**
- Modify: `src/services/user_service.py`
- Modify: `src/database/database.py`
- Modify: `src/database/user_repo.py`
- Modify: `tests/test_database_repos.py`

- [ ] **Step 1: Capture baseline**

Run: `pytest tests/ -x -q`
Expected: green.

- [ ] **Step 2: Find callers**

Run: `grep -rn "update_user_llm_preference\|update_user_openai_model_preference\|update_llm_preference\|update_openai_model_preference" src/ tests/ 2>/dev/null | grep -v __pycache__`

Note any remaining call sites. If after Tasks 13 & 14 there are still callers other than the definitions themselves, fix them in this step before deleting the methods.

- [ ] **Step 3: Delete the methods**

1. In `src/services/user_service.py`, delete the methods `update_user_llm_preference` and `update_user_openai_model_preference` (find them with `grep -n "def update_user_" src/services/user_service.py`).

2. In `src/database/database.py`, delete the methods `update_user_llm_preference` (currently lines 262-269) and `update_user_openai_model_preference` (currently lines 280-287).

3. In `src/database/user_repo.py`, delete the methods `update_llm_preference` and `update_openai_model_preference` (currently lines 36-50).

- [ ] **Step 4: Remove obsolete tests**

In `tests/test_database_repos.py`, delete the tests `test_update_llm_preference` and `test_update_openai_model_preference`. Leave `test_create_and_get_user` and the rest unchanged.

- [ ] **Step 5: Run the full suite**

Run: `pytest tests/ -x -q`
Expected: All tests pass.

- [ ] **Step 6: Smoke-test**

Run: `python -c "from src.services.user_service import UserService; svc = UserService(); print('ok', hasattr(svc, 'update_user_llm_preference'))"`
Expected: `ok False`.

- [ ] **Step 7: Commit**

```bash
git add src/services/user_service.py src/database/database.py src/database/user_repo.py tests/test_database_repos.py
git commit -m "chore(db): drop unused per-user LLM/model preference methods"
```

---

## Final verification

- [ ] **Step 1: Run the full test suite verbose**

Run: `pytest tests/ -v`
Expected: All tests pass.

- [ ] **Step 2: Regression greps**

Run each and confirm the expected number of matches:

```bash
grep -rn "generate_protocol_with_fallback" src/ tests/ | grep -v __pycache__
grep -rn "AnthropicProvider\|YandexGPTProvider" src/ tests/ | grep -v __pycache__
grep -rn "preferred_openai_model_key" src/ tests/ --include='*.py' | grep -v __pycache__
grep -rn "update_user_llm_preference\|update_user_openai_model_preference" src/ tests/ | grep -v __pycache__
```

Expected:
- `generate_protocol_with_fallback`: 0 matches.
- `AnthropicProvider`/`YandexGPTProvider`: 0 matches.
- `preferred_openai_model_key`: matches only in `src/models/user.py` (Pydantic field, legacy) and `src/database/database.py` (`CREATE TABLE users` and the `ALTER TABLE` migration — both intentional per spec D5).
- `update_user_llm_preference`/`update_user_openai_model_preference`: 0 matches.

- [ ] **Step 3: Manual smoke (optional but recommended)**

Start the bot locally with a valid `.env`. Verify:
- `/start` shows the welcome message without any "Модель: …" line for non-admin users.
- `/settings` for non-admin: 4 buttons, no "Модель ИИ".
- `/settings` for admin: 5 buttons, top one is "🤖 Модель ИИ"; clicking it shows the preset list with ✅ next to the active one.
- Picking a different preset updates `app_settings.active_model_key` (check with `sqlite3 bot.db "SELECT * FROM app_settings;"`).
- Sending an audio file as a non-admin: bot proceeds directly to processing without asking which LLM/model to use.
- `/models` shows the ⭐ marker next to the active preset; attempting to delete the active preset shows the friendly error message; the detail card has a "▶️ Сделать активной" button only on non-active enabled presets.

---

## Out of scope (deferred)

- `.env` override (`ACTIVE_MODEL_KEY=…`) for seed.
- Per-chat/per-template model selection.
- Reinstating Anthropic/Yandex providers.
- `ALTER TABLE users DROP COLUMN preferred_llm`/`preferred_openai_model_key`.
