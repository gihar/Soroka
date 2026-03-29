# Phase A: Foundation — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Establish CI/CD, split monolithic files, move root-level modules into `src/`, add tests for critical paths.

**Architecture:** Incremental refactoring with backward-compatible re-exports from root. Each task produces a working bot. Repository pattern over monolithic Database class. LLM providers split by class into separate modules.

**Tech Stack:** Python 3.11, ruff, mypy, pytest, pytest-asyncio, GitHub Actions

---

## Task 1: CI/CD Pipeline + Linting + Type Checking

**Files:**
- Create: `pyproject.toml`
- Create: `requirements-dev.txt`
- Create: `Makefile`
- Create: `.github/workflows/ci.yml`

**Step 1: Create pyproject.toml**

```toml
[project]
name = "soroka"
version = "1.0.0"
requires-python = ">=3.11"

[tool.ruff]
target-version = "py311"
line-length = 120
src = ["src", "."]

[tool.ruff.lint]
select = ["E", "F", "W", "I"]
ignore = [
    "E501",  # line too long — relax during migration
]

[tool.ruff.lint.isort]
known-first-party = ["src"]

[tool.mypy]
python_version = "3.11"
ignore_missing_imports = true
check_untyped_defs = false
warn_return_any = false

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
python_files = ["test_*.py"]
python_functions = ["test_*"]
addopts = "-v --tb=short"
```

**Step 2: Create requirements-dev.txt**

```
ruff>=0.8.0
mypy>=1.13.0
pytest>=8.3.0
pytest-asyncio>=0.24.0
pytest-cov>=6.0.0
pre-commit>=4.0.0
```

**Step 3: Create Makefile**

```makefile
.PHONY: lint format test check install-dev

lint:
	ruff check . --fix
	ruff format --check .

format:
	ruff format .
	ruff check . --fix

test:
	pytest tests/ -v

test-cov:
	pytest tests/ -v --cov=src --cov-report=term-missing

check: lint test

install-dev:
	pip install -r requirements-dev.txt
```

**Step 4: Create .github/workflows/ci.yml**

```yaml
name: CI

on:
  push:
    branches: [main, optimize/*]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install ruff
      - run: ruff check .
      - run: ruff format --check .

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - run: pytest tests/ -v --tb=short
```

**Step 5: Run lint to see current state**

```bash
pip install -r requirements-dev.txt
ruff check . --statistics
```

Expected: Many warnings (we'll fix incrementally). No blockers.

**Step 6: Commit**

```bash
git add pyproject.toml requirements-dev.txt Makefile .github/workflows/ci.yml
git commit -m "chore: add CI/CD pipeline with ruff, mypy, pytest"
```

---

## Task 2: Move config.py into src/

**Files:**
- Move: `config.py` -> `src/config.py`
- Create: `config.py` (root re-export shim)

**Step 1: Copy config.py to src/**

Copy `config.py` to `src/config.py`. Content stays identical.

**Step 2: Replace root config.py with re-export shim**

```python
"""Backward-compatible re-export. Real module lives in src/config.py."""
from src.config import Settings, OpenAIModelPreset, settings

__all__ = ["Settings", "OpenAIModelPreset", "settings"]
```

**Step 3: Verify all imports work**

```bash
python -c "from config import settings; print(settings.telegram_token[:5] if settings.telegram_token else 'NO_TOKEN')"
python -c "from src.config import settings; print(type(settings))"
```

Expected: Both imports resolve. Settings object loads from .env.

**Step 4: Run existing tests**

```bash
make test
```

Expected: All 7 existing test files pass.

**Step 5: Commit**

```bash
git add src/config.py config.py
git commit -m "refactor: move config.py into src/ with root re-export shim"
```

---

## Task 3: Move database.py into src/database/ + Repository Pattern

**Files:**
- Create: `src/database/__init__.py`
- Move: `database.py` -> `src/database/database.py`
- Create: `database.py` (root re-export shim)
- Create: `src/database/user_repo.py`
- Create: `src/database/template_repo.py`
- Create: `src/database/feedback_repo.py`
- Create: `src/database/metrics_repo.py`
- Create: `src/database/queue_repo.py`

### Step 1: Create src/database/ directory and move database.py

Copy `database.py` to `src/database/database.py`. Update its import:

```python
# In src/database/database.py, change line 8:
# OLD: from config import settings
# NEW:
from src.config import settings
```

### Step 2: Create src/database/__init__.py

```python
"""Database package with repository pattern."""
from .database import Database, db

__all__ = ["Database", "db"]
```

### Step 3: Replace root database.py with re-export shim

```python
"""Backward-compatible re-export. Real module lives in src/database/."""
from src.database import Database, db

__all__ = ["Database", "db"]
```

### Step 4: Verify imports

```bash
python -c "from database import db; print(type(db))"
python -c "from src.database import db; print(type(db))"
```

### Step 5: Extract UserRepository

Create `src/database/user_repo.py`:

```python
"""User data access."""
from typing import Optional, Dict
from loguru import logger


class UserRepository:
    """Repository for user CRUD operations."""

    def __init__(self, database):
        self._db = database

    async def get_user(self, telegram_id: int) -> Optional[Dict]:
        """Get user by Telegram ID."""
        async with self._db._connect() as db:
            db.row_factory = self._db._dict_factory
            cursor = await db.execute(
                "SELECT * FROM users WHERE telegram_id = ?",
                (telegram_id,)
            )
            return await cursor.fetchone()

    async def create_user(self, telegram_id: int, username: str = None,
                          first_name: str = None, last_name: str = None) -> None:
        """Create a new user."""
        async with self._db._connect() as db:
            await db.execute(
                """INSERT OR IGNORE INTO users (telegram_id, username, first_name, last_name)
                   VALUES (?, ?, ?, ?)""",
                (telegram_id, username, first_name, last_name)
            )
            await db.commit()

    async def update_llm_preference(self, telegram_id: int, llm_provider: str) -> None:
        """Update user's preferred LLM provider."""
        async with self._db._connect() as db:
            await db.execute(
                "UPDATE users SET preferred_llm = ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
                (llm_provider, telegram_id)
            )
            await db.commit()

    async def update_openai_model_preference(self, telegram_id: int, model_key: str) -> None:
        """Update user's preferred OpenAI model."""
        async with self._db._connect() as db:
            await db.execute(
                "UPDATE users SET preferred_openai_model_key = ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
                (model_key, telegram_id)
            )
            await db.commit()

    async def update_protocol_output_preference(self, telegram_id: int, mode: str) -> None:
        """Update user's preferred protocol output mode."""
        async with self._db._connect() as db:
            await db.execute(
                "UPDATE users SET protocol_output_mode = ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
                (mode, telegram_id)
            )
            await db.commit()
```

**Note:** The actual method bodies should be extracted verbatim from the existing `database.py` methods (lines 222-268). The code above shows the pattern — the implementer must read the actual Database methods and extract their SQL logic into the repository.

### Step 6: Extract remaining repositories

Follow the same pattern for:
- `template_repo.py` — extract from Database methods at lines 271-508
- `feedback_repo.py` — extract from lines 659-714
- `metrics_repo.py` — extract from lines 715-762
- `queue_repo.py` — extract from lines 764-865

Each repository takes `database` in its constructor and uses `self._db._connect()` for connections.

### Step 7: Update __init__.py with repositories

```python
"""Database package with repository pattern."""
from .database import Database, db
from .user_repo import UserRepository
from .template_repo import TemplateRepository
from .feedback_repo import FeedbackRepository
from .metrics_repo import MetricsRepository
from .queue_repo import QueueRepository

# Convenience instances
user_repo = UserRepository(db)
template_repo = TemplateRepository(db)
feedback_repo = FeedbackRepository(db)
metrics_repo = MetricsRepository(db)
queue_repo = QueueRepository(db)

__all__ = [
    "Database", "db",
    "UserRepository", "TemplateRepository", "FeedbackRepository",
    "MetricsRepository", "QueueRepository",
    "user_repo", "template_repo", "feedback_repo",
    "metrics_repo", "queue_repo",
]
```

### Step 8: Verify and commit

```bash
python -c "from src.database import user_repo, template_repo; print('Repos OK')"
make test
git add src/database/ database.py
git commit -m "refactor: move database.py to src/database/ with repository pattern"
```

**Important:** Do NOT update existing service imports yet. Services still use `from database import db` which works via the root shim. Repository migration of services is a separate future task.

---

## Task 4: Split llm_providers.py into src/llm/

**Files:**
- Create: `src/llm/__init__.py`
- Create: `src/llm/base.py`
- Create: `src/llm/json_utils.py`
- Create: `src/llm/prompt_builders.py`
- Create: `src/llm/providers/__init__.py`
- Create: `src/llm/providers/openai_provider.py`
- Create: `src/llm/providers/anthropic_provider.py`
- Create: `src/llm/providers/yandex_provider.py`
- Create: `src/llm/manager.py`
- Modify: `llm_providers.py` (replace with re-export shim)

### Step 1: Create src/llm/json_utils.py

Extract `safe_json_parse()` function (lines 53-170 from `llm_providers.py`). No changes to logic — just move.

### Step 2: Create src/llm/base.py

Extract `LLMProvider` ABC (lines 171-182):

```python
"""Abstract base class for LLM providers."""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Tuple


class LLMProvider(ABC):
    """Base class for all LLM providers."""

    @abstractmethod
    async def generate_protocol(
        self,
        transcription: str,
        template_variables: Dict[str, str],
        diarization_data: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Generate protocol from transcription."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if provider is available."""
        pass
```

### Step 3: Create src/llm/prompt_builders.py

Extract `_build_system_prompt()` (line 188) and `_build_user_prompt()` (line 352) from `llm_providers.py`. These are module-level functions ~440 lines total.

### Step 4: Create provider files

- `src/llm/providers/openai_provider.py` — Extract `OpenAIProvider` class (lines 628-809)
- `src/llm/providers/anthropic_provider.py` — Extract `AnthropicProvider` class (lines 810-974)
- `src/llm/providers/yandex_provider.py` — Extract `YandexGPTProvider` class (lines 975-1065)

Each provider file imports from `src.llm.base`, `src.llm.json_utils`, `src.llm.prompt_builders`.

### Step 5: Create src/llm/manager.py

Extract `LLMManager` class (lines 1066-1132) and `generate_protocol()` wrapper function (lines 1134-1201).

### Step 6: Create src/llm/__init__.py

```python
"""LLM providers package."""
from .manager import LLMManager, generate_protocol
from .json_utils import safe_json_parse
from .base import LLMProvider

# Global singleton (matches original llm_providers.py behavior)
llm_manager = LLMManager()

__all__ = [
    "LLMProvider", "LLMManager",
    "llm_manager", "safe_json_parse", "generate_protocol",
]
```

### Step 7: Replace root llm_providers.py with re-export shim

```python
"""Backward-compatible re-export. Real module lives in src/llm/."""
from src.llm import llm_manager, safe_json_parse, generate_protocol, LLMProvider, LLMManager

__all__ = ["llm_manager", "safe_json_parse", "generate_protocol", "LLMProvider", "LLMManager"]
```

### Step 8: Verify and commit

```bash
python -c "from llm_providers import llm_manager, safe_json_parse; print('LLM OK')"
python -c "from src.llm import llm_manager; print(type(llm_manager))"
python -c "from src.llm.providers.openai_provider import OpenAIProvider; print('OpenAI OK')"
make test
git add src/llm/ llm_providers.py
git commit -m "refactor: split llm_providers.py into src/llm/ package (6 modules)"
```

---

## Task 5: Split callback_handlers.py into src/handlers/callbacks/

**Files:**
- Create: `src/handlers/callbacks/__init__.py`
- Create: `src/handlers/callbacks/helpers.py`
- Create: `src/handlers/callbacks/llm_callbacks.py`
- Create: `src/handlers/callbacks/template_callbacks.py`
- Create: `src/handlers/callbacks/template_mgmt_callbacks.py`
- Create: `src/handlers/callbacks/settings_callbacks.py`
- Create: `src/handlers/callbacks/processing_callbacks.py`
- Create: `src/handlers/callbacks/speaker_mapping_callbacks.py`
- Modify: `src/handlers/__init__.py` (update import)
- Delete: `src/handlers/callback_handlers.py` (after migration verified)

### Step 1: Create helpers.py

Extract from `callback_handlers.py`:
- `_safe_callback_answer()` (line 15)
- `_fix_markdown_tags()` (line 2139)
- `_send_long_message()` (line 2157)

### Step 2: Create llm_callbacks.py

Extract handlers with prefixes `set_llm_`, `reset_llm_preference`, `select_llm_`:
- `set_llm_callback()` (line 35)
- `reset_llm_preference_callback()` (line 56)
- `select_llm_callback()` (line 306)

Create function `setup_llm_callbacks(user_service, template_service, llm_service, processing_service) -> Router` that registers these handlers.

### Step 3: Create template_callbacks.py

Extract 11 handlers for template selection (lines 73-275 + 803-1092):
- `select_template_once_callback`, `select_category_callback`, `select_template_id_callback`, `select_template_callback`, `use_default_template_callback`, `show_all_templates_callback`
- `template_category_callback`, `file_template_category_callback`, `back_to_template_categories_callback`, `back_to_template_selection_callback`
- `quick_category_callback`, `quick_template_callback`

Create function `setup_template_callbacks(...) -> Router`.

### Step 4: Create template_mgmt_callbacks.py

Extract 7 handlers for template management:
- `delete_template_prompt_callback`, `confirm_delete_template_callback`, `back_to_templates_callback`
- `set_default_template_callback`, `reset_default_template_callback`
- `settings_default_template_callback`, `quick_set_default_callback`

Create function `setup_template_mgmt_callbacks(...) -> Router`.

### Step 5: Create settings_callbacks.py

Extract 8 handlers:
- `settings_preferred_llm_callback`, `settings_openai_model_callback`, `set_openai_model_callback`
- `reset_openai_model_preference_callback`, `settings_protocol_output_callback`
- `set_protocol_output_mode_callback`, `settings_reset_callback`, `back_to_settings_callback`

Create function `setup_settings_callbacks(...) -> Router`.

### Step 6: Create processing_callbacks.py

Extract 3 handlers:
- `set_transcription_mode_callback`, `cancel_task_callback`, `_cancel_task_callback`

Create function `setup_processing_callbacks(...) -> Router`.

### Step 7: Create speaker_mapping_callbacks.py

Extract 5 handlers:
- `speaker_mapping_change_callback`, `speaker_mapping_select_callback`
- `speaker_mapping_cancel_callback`, `speaker_mapping_confirm_callback`
- `speaker_mapping_skip_callback`

Create function `setup_speaker_mapping_callbacks(...) -> Router`.

### Step 8: Create callbacks/__init__.py aggregator

```python
"""Callback handlers aggregated from domain-specific modules."""
from aiogram import Router

from src.services import UserService, TemplateService, EnhancedLLMService, ProcessingService

from .llm_callbacks import setup_llm_callbacks
from .template_callbacks import setup_template_callbacks
from .template_mgmt_callbacks import setup_template_mgmt_callbacks
from .settings_callbacks import setup_settings_callbacks
from .processing_callbacks import setup_processing_callbacks
from .speaker_mapping_callbacks import setup_speaker_mapping_callbacks


def setup_callback_handlers(
    user_service: UserService,
    template_service: TemplateService,
    llm_service: EnhancedLLMService,
    processing_service: ProcessingService,
) -> Router:
    """Aggregate all callback routers into one."""
    router = Router()
    router.include_router(setup_llm_callbacks(user_service, template_service, llm_service, processing_service))
    router.include_router(setup_template_callbacks(user_service, template_service, llm_service, processing_service))
    router.include_router(setup_template_mgmt_callbacks(user_service, template_service, llm_service, processing_service))
    router.include_router(setup_settings_callbacks(user_service, template_service, llm_service, processing_service))
    router.include_router(setup_processing_callbacks(user_service, template_service, llm_service, processing_service))
    router.include_router(setup_speaker_mapping_callbacks(user_service, template_service, llm_service, processing_service))
    return router
```

### Step 9: Update src/handlers/__init__.py

```python
"""Telegram bot handlers."""
from .command_handlers import setup_command_handlers
from .callbacks import setup_callback_handlers
from .message_handlers import setup_message_handlers
from .template_handlers import setup_template_handlers

__all__ = [
    "setup_command_handlers",
    "setup_callback_handlers",
    "setup_message_handlers",
    "setup_template_handlers",
]
```

### Step 10: Verify and delete old file

```bash
python -c "from handlers import setup_callback_handlers; print('Callbacks OK')"
make test
```

If all passes, delete `src/handlers/callback_handlers.py`.

```bash
git add src/handlers/callbacks/ src/handlers/__init__.py
git rm src/handlers/callback_handlers.py
git commit -m "refactor: split callback_handlers.py (2216 lines) into 7 domain modules"
```

---

## Task 6: Split processing_service.py into src/services/processing/

**Files:**
- Create: `src/services/processing/__init__.py`
- Create: `src/services/processing/protocol_formatter.py`
- Create: `src/services/processing/llm_generation.py`
- Create: `src/services/processing/processing_history.py`
- Move: `src/services/processing_service.py` -> `src/services/processing/processing_service.py`
- Modify: `src/services/__init__.py` (update import path)

### Step 1: Create protocol_formatter.py

Extract formatting methods from ProcessingService:
- `_format_protocol()` (line 1650)
- `_convert_complex_to_markdown()` (line 1412)
- `_format_dict_to_text()` (line 1430)
- `_format_list_to_text()` (line 1504)
- `_format_speaker_mapping_message()` (line 49)

Create class `ProtocolFormatter` with these as methods.

### Step 2: Create llm_generation.py

Extract LLM-related methods:
- `_optimized_llm_generation()` (line 1089)
- `_generate_llm_response()` (line 1377)
- `_post_process_llm_result()` (line 1398)
- `_fix_json_in_text()` (line 1527)
- `_get_model_display_name()` (line 1360)
- `_get_template_variables_from_template()` (line 1285)

Create class `LLMGenerationService` with these as methods.

### Step 3: Create processing_history.py

Extract persistence/utility methods:
- `_save_processing_history()` (line 183)
- `_calculate_file_hash()` (line 1574)
- `_cleanup_temp_file()` (line 1617)
- `_generate_result_cache_key()` (line 1627)

Create class `ProcessingHistoryService` with these as methods.

### Step 4: Refactor ProcessingService as orchestrator

Move to `src/services/processing/processing_service.py`. ProcessingService now:
1. Inherits `BaseProcessingService` (unchanged)
2. Uses `ProtocolFormatter`, `LLMGenerationService`, `ProcessingHistoryService` via composition
3. Keeps only orchestration methods: `process_file()`, `_process_file_optimized()`, `continue_processing_after_mapping_confirmation()`, `_suggest_template_if_needed()`, performance/monitoring methods

### Step 5: Create src/services/processing/__init__.py

```python
"""Processing service package."""
from .processing_service import ProcessingService

__all__ = ["ProcessingService"]
```

### Step 6: Update src/services/__init__.py

Change line 11:
```python
# OLD: from .processing_service import ProcessingService
# NEW:
from .processing import ProcessingService
```

### Step 7: Verify and commit

```bash
python -c "from services import ProcessingService; print('Processing OK')"
python -c "from src.services.processing_service import ProcessingService; print('Compat OK')"
make test
git add src/services/processing/ src/services/__init__.py
git rm src/services/processing_service.py
git commit -m "refactor: split processing_service.py (1942 lines) into 4 focused modules"
```

---

## Task 7: Tests for Critical Paths

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/test_json_utils.py`
- Create: `tests/test_database_repos.py`
- Create: `tests/test_llm_manager.py`
- Create: `tests/test_protocol_formatter.py`

### Step 1: Create tests/conftest.py

```python
"""Shared test fixtures."""
import asyncio
import pytest
import os

# Set test environment before importing anything
os.environ.setdefault("TELEGRAM_TOKEN", "test:fake-token")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def test_db():
    """In-memory SQLite database for testing."""
    from src.database.database import Database
    db = Database(db_path=":memory:")
    await db.init_db()
    return db


@pytest.fixture
async def user_repo(test_db):
    """UserRepository backed by in-memory DB."""
    from src.database.user_repo import UserRepository
    return UserRepository(test_db)


@pytest.fixture
async def template_repo(test_db):
    """TemplateRepository backed by in-memory DB."""
    from src.database.template_repo import TemplateRepository
    return TemplateRepository(test_db)
```

### Step 2: Write tests for safe_json_parse

Create `tests/test_json_utils.py`:

```python
"""Tests for LLM JSON parsing utilities."""
from src.llm.json_utils import safe_json_parse


def test_parse_valid_json():
    result = safe_json_parse('{"key": "value"}')
    assert result == {"key": "value"}


def test_parse_json_in_markdown_block():
    text = '```json\n{"key": "value"}\n```'
    result = safe_json_parse(text)
    assert result == {"key": "value"}


def test_parse_json_with_surrounding_text():
    text = 'Here is the result: {"key": "value"} done.'
    result = safe_json_parse(text)
    assert result == {"key": "value"}


def test_parse_json_with_trailing_comma():
    text = '{"key": "value",}'
    result = safe_json_parse(text)
    assert result == {"key": "value"}


def test_parse_json_with_comments():
    text = '{"key": "value" // comment\n}'
    result = safe_json_parse(text)
    assert result == {"key": "value"}


def test_parse_empty_string_raises():
    import pytest
    with pytest.raises((ValueError, Exception)):
        safe_json_parse("")


def test_parse_invalid_json_raises():
    import pytest
    with pytest.raises((ValueError, Exception)):
        safe_json_parse("not json at all")


def test_parse_with_bom():
    text = '\ufeff{"key": "value"}'
    result = safe_json_parse(text)
    assert result == {"key": "value"}
```

Run: `pytest tests/test_json_utils.py -v`

### Step 3: Write tests for database repositories

Create `tests/test_database_repos.py`:

```python
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
async def test_update_llm_preference(user_repo):
    await user_repo.create_user(telegram_id=12345)
    await user_repo.update_llm_preference(12345, "anthropic")
    user = await user_repo.get_user(12345)
    assert user["preferred_llm"] == "anthropic"


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
async def test_delete_template(template_repo):
    tid = await template_repo.create_template(name="ToDelete", content="x")
    await template_repo.delete_template(tid)
    template = await template_repo.get_template(tid)
    assert template is None
```

Run: `pytest tests/test_database_repos.py -v`

### Step 4: Write tests for LLM manager fallback

Create `tests/test_llm_manager.py`:

```python
"""Tests for LLM manager fallback logic."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_manager_uses_requested_provider():
    """Manager should use the requested provider when available."""
    from src.llm.manager import LLMManager

    manager = LLMManager()

    mock_provider = MagicMock()
    mock_provider.is_available.return_value = True
    mock_provider.generate_protocol = AsyncMock(
        return_value=({"summary": "test"}, {"usage": {}})
    )
    manager.providers = {"test_provider": mock_provider}

    result, meta = await manager.generate_protocol(
        provider_name="test_provider",
        transcription="test text",
        template_variables={"summary": "Summary"},
    )
    assert result == {"summary": "test"}
    mock_provider.generate_protocol.assert_called_once()


@pytest.mark.asyncio
async def test_manager_fallback_on_failure():
    """Manager should fall back to next provider on failure."""
    from src.llm.manager import LLMManager

    manager = LLMManager()

    failing_provider = MagicMock()
    failing_provider.is_available.return_value = True
    failing_provider.generate_protocol = AsyncMock(side_effect=Exception("API down"))

    working_provider = MagicMock()
    working_provider.is_available.return_value = True
    working_provider.generate_protocol = AsyncMock(
        return_value=({"summary": "fallback"}, {"usage": {}})
    )

    manager.providers = {"primary": failing_provider, "backup": working_provider}

    result, meta = await manager.generate_protocol_with_fallback(
        transcription="test text",
        template_variables={"summary": "Summary"},
    )
    assert result == {"summary": "fallback"}
```

Run: `pytest tests/test_llm_manager.py -v`

### Step 5: Run full test suite with coverage

```bash
pytest tests/ -v --cov=src --cov-report=term-missing
```

Target: 40%+ coverage on touched modules (json_utils, database repos, manager).

### Step 6: Commit

```bash
git add tests/
git commit -m "test: add tests for database repos, JSON parsing, LLM fallback (40%+ target)"
```

---

## Verification Checklist (after all tasks)

After completing all 7 tasks:

1. `make lint` passes
2. `make test` passes (all existing + new tests green)
3. Bot starts: `python main.py` (verify manually, Ctrl+C after startup)
4. Root imports work:
   ```bash
   python -c "from config import settings; print('OK')"
   python -c "from database import db; print('OK')"
   python -c "from llm_providers import llm_manager; print('OK')"
   ```
5. New imports work:
   ```bash
   python -c "from src.config import settings; print('OK')"
   python -c "from src.database import db, user_repo; print('OK')"
   python -c "from src.llm import llm_manager; print('OK')"
   python -c "from src.services import ProcessingService; print('OK')"
   python -c "from src.handlers import setup_callback_handlers; print('OK')"
   ```
6. Git log shows 7 clean commits, one per task
