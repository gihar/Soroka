"""Model preset data access."""

from typing import Any, Dict, List, Optional

import aiosqlite
from loguru import logger

from src.exceptions.configuration import ActivePresetDeletionError

# Whitelist of fields allowed in update_field
_ALLOWED_FIELDS = frozenset({
    "name", "model", "base_url", "api_key",
    "admin_only", "is_enabled",
})


class ModelPresetRepository:
    """Repository for model preset CRUD operations."""

    def __init__(self, database):
        self._db = database

    async def get_all(self) -> List[Dict[str, Any]]:
        """Get all presets ordered by created_at."""
        async with aiosqlite.connect(self._db.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM model_presets ORDER BY created_at"
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_enabled(self) -> List[Dict[str, Any]]:
        """Get enabled presets ordered by created_at."""
        async with aiosqlite.connect(self._db.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM model_presets WHERE is_enabled = 1 ORDER BY created_at"
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_available_for_user(self, user_id: int) -> List[Dict[str, Any]]:
        """Get enabled presets available to a specific user.

        Admin-only presets are included only when user_id belongs to an admin.
        """
        from src.utils.admin_utils import is_admin

        presets = await self.get_enabled()
        if is_admin(user_id):
            return presets
        return [p for p in presets if not p.get("admin_only")]

    async def get_by_key(self, key: str) -> Optional[Dict[str, Any]]:
        """Get a single preset by its unique key."""
        async with aiosqlite.connect(self._db.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM model_presets WHERE key = ?",
                (key,),
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def upsert(
        self,
        key: str,
        name: str,
        model: str,
        base_url: str,
        api_key: Optional[str] = None,
        admin_only: bool = False,
    ) -> None:
        """Insert or update a preset by key.

        When api_key is None the existing value is preserved via COALESCE.
        """
        async with aiosqlite.connect(self._db.db_path) as db:
            await db.execute(
                """
                INSERT INTO model_presets (key, name, model, base_url, api_key, admin_only)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    name = excluded.name,
                    model = excluded.model,
                    base_url = excluded.base_url,
                    api_key = COALESCE(excluded.api_key, model_presets.api_key),
                    admin_only = excluded.admin_only
                """,
                (key, name, model, base_url, api_key, int(admin_only)),
            )
            await db.commit()

        # Invalidate any cached OpenAI client built from a previous version of this
        # preset, so the next request rebuilds with current base_url/api_key.
        # Best-effort: never block the upsert on cache invalidation errors.
        try:
            from src.llm import llm_manager
            provider = llm_manager.providers.get("openai")
            if provider is not None:
                provider.invalidate_cache_for_base_url(base_url)
        except Exception as e:
            logger.warning(
                f"Failed to invalidate OpenAI client cache for preset '{key}': {e}"
            )

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

        async with aiosqlite.connect(self._db.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            if field == "is_enabled" and int(value) == 0:
                await self._raise_if_active(db, key, operation="отключить")
            cursor = await db.execute(
                f"UPDATE model_presets SET {field} = ? WHERE key = ?",
                (value, key),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def delete(self, key: str) -> bool:
        """Delete a preset by key. Returns True if a row was deleted.

        Raises `ActivePresetDeletionError` if `key` is the globally active model.
        """
        async with aiosqlite.connect(self._db.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            await self._raise_if_active(db, key, operation="удалить")
            cursor = await db.execute(
                "DELETE FROM model_presets WHERE key = ?",
                (key,),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def _raise_if_active(self, db, key: str, operation: str) -> None:
        """Raise ActivePresetDeletionError if `key` is the globally active preset.

        Uses the open transaction `db` so the check and the mutation that follows
        run under a single write lock.
        """
        cursor = await db.execute(
            "SELECT value FROM app_settings WHERE key = 'active_model_key'"
        )
        row = await cursor.fetchone()
        if row is not None and row[0] == key:
            await db.rollback()
            raise ActivePresetDeletionError(
                f"Нельзя {operation} активный пресет '{key}'. "
                "Сначала выберите другой пресет в /settings → Модель ИИ."
            )

    async def sync_from_config(self) -> int:
        """Import presets from settings.openai_models into DB via upsert.

        Returns the number of presets synced.
        """
        from src.config import settings

        fallback_base_url = settings.openai_base_url or "https://api.openai.com/v1"
        count = 0

        for preset in settings.openai_models:
            base_url = preset.base_url or fallback_base_url
            await self.upsert(
                key=preset.key,
                name=preset.name,
                model=preset.model,
                base_url=base_url,
            )
            count += 1

        if count:
            logger.info(f"Synced {count} model preset(s) from config")

        return count
