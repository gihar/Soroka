"""Application-wide key-value settings (admin-controlled).

Stores small, global pieces of state that are not user-scoped — most notably
`active_model_key`, the globally selected AI model preset.
"""

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
        async with self._db.connect() as db:
            cursor = await db.execute(
                "SELECT value FROM app_settings WHERE key = ?",
                (key,),
            )
            row = await cursor.fetchone()
            return row[0] if row else None

    async def set(self, key: str, value: str, admin_id: Optional[int]) -> None:
        """UPSERT `key` to `value`, recording `admin_id` as `updated_by`."""
        async with self._db.connect() as db:
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
        async with self._db.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT is_enabled FROM model_presets WHERE key = ?",
                (preset_key,),
            )
            row = await cursor.fetchone()
            if row is None:
                await db.rollback()
                raise AdminConfigurationError(
                    f"Пресет '{preset_key}' не существует"
                )
            if not row[0]:
                await db.rollback()
                raise AdminConfigurationError(
                    f"Пресет '{preset_key}' отключён и не может быть активным"
                )
            await db.execute(
                """
                INSERT INTO app_settings (key, value, updated_by, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_by = excluded.updated_by,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (_ACTIVE_MODEL_KEY, preset_key, admin_id),
            )
            await db.commit()

        logger.info(
            f"active_model_key set to '{preset_key}' by admin {admin_id}"
        )
