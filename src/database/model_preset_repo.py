"""Model preset data access."""

import aiosqlite
from typing import Optional, List, Dict, Any
from loguru import logger


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

    async def update_field(self, key: str, field: str, value: Any) -> bool:
        """Update a single field for a preset identified by key.

        Returns True when a row was affected.
        Raises ValueError if the field name is not in the whitelist.
        """
        if field not in _ALLOWED_FIELDS:
            raise ValueError(
                f"Field '{field}' is not allowed. "
                f"Allowed fields: {', '.join(sorted(_ALLOWED_FIELDS))}"
            )

        async with aiosqlite.connect(self._db.db_path) as db:
            cursor = await db.execute(
                f"UPDATE model_presets SET {field} = ? WHERE key = ?",
                (value, key),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def delete(self, key: str) -> bool:
        """Delete a preset by key. Returns True if a row was deleted."""
        async with aiosqlite.connect(self._db.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM model_presets WHERE key = ?",
                (key,),
            )
            await db.commit()
            return cursor.rowcount > 0

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
