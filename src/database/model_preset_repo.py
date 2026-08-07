"""Model preset data access."""

import json
from typing import Any, Dict, List, Optional

from loguru import logger

from src.exceptions.configuration import ActivePresetDeletionError

# Whitelist of fields allowed in update_field
_ALLOWED_FIELDS = frozenset({
    "name", "model", "base_url", "api_key",
    "admin_only", "is_enabled",
})

# Provider params stored as a JSON object; the repository is their boundary —
# callers get dicts, never raw JSON text.
_JSON_FIELDS = ("extra_body", "extra_headers")


def _decode_params(key: str, field: str, raw: Any) -> Dict[str, Any]:
    """Decode a stored JSON object into a dict; anything unusable becomes {}."""
    if raw in (None, ""):
        return {}
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError) as e:
        logger.warning(f"Пресет '{key}': поле {field} не разобралось как JSON ({e})")
        return {}
    if not isinstance(decoded, dict):
        logger.warning(f"Пресет '{key}': поле {field} — не объект, игнорируется")
        return {}
    return decoded


def _encode_params(params: Optional[Dict[str, Any]]) -> Optional[str]:
    """Encode provider params for storage; None stays None (means «not set»)."""
    if params is None:
        return None
    return json.dumps(params, ensure_ascii=False)


def _to_preset(row) -> Dict[str, Any]:
    """Row → preset dict with provider params decoded into dicts."""
    preset = dict(row)
    for field in _JSON_FIELDS:
        preset[field] = _decode_params(preset.get("key", "?"), field, preset.get(field))
    return preset


class ModelPresetRepository:
    """Repository for model preset CRUD operations."""

    def __init__(self, database):
        self._db = database

    async def get_all(self) -> List[Dict[str, Any]]:
        """Get all presets ordered by created_at."""
        async with self._db.connect() as db:
            cursor = await db.execute(
                "SELECT * FROM model_presets ORDER BY created_at"
            )
            rows = await cursor.fetchall()
            return [_to_preset(row) for row in rows]

    async def get_enabled(self) -> List[Dict[str, Any]]:
        """Get enabled presets ordered by created_at."""
        async with self._db.connect() as db:
            cursor = await db.execute(
                "SELECT * FROM model_presets WHERE is_enabled = 1 ORDER BY created_at"
            )
            rows = await cursor.fetchall()
            return [_to_preset(row) for row in rows]

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
        async with self._db.connect() as db:
            cursor = await db.execute(
                "SELECT * FROM model_presets WHERE key = ?",
                (key,),
            )
            row = await cursor.fetchone()
            return _to_preset(row) if row else None

    async def upsert(
        self,
        key: str,
        name: str,
        model: str,
        base_url: str,
        api_key: Optional[str] = None,
        admin_only: bool = False,
        extra_body: Optional[Dict[str, Any]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        analysis_model: Optional[str] = None,
        mapping_model: Optional[str] = None,
    ) -> None:
        """Insert or update a preset by key.

        When api_key, provider params or a cheap-step model is None the existing
        value is preserved via COALESCE: a resync from config never wipes what an
        admin set by hand. An empty cheap-step model means «the preset's main
        model» (ADR-0007), so it needs no value of its own.
        """
        async with self._db.connect() as db:
            await db.execute(
                """
                INSERT INTO model_presets (
                    key, name, model, base_url, api_key, admin_only,
                    extra_body, extra_headers, analysis_model, mapping_model
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    name = excluded.name,
                    model = excluded.model,
                    base_url = excluded.base_url,
                    api_key = COALESCE(excluded.api_key, model_presets.api_key),
                    admin_only = excluded.admin_only,
                    extra_body = COALESCE(excluded.extra_body, model_presets.extra_body),
                    extra_headers = COALESCE(
                        excluded.extra_headers, model_presets.extra_headers
                    ),
                    analysis_model = COALESCE(
                        excluded.analysis_model, model_presets.analysis_model
                    ),
                    mapping_model = COALESCE(
                        excluded.mapping_model, model_presets.mapping_model
                    )
                """,
                (
                    key, name, model, base_url, api_key, int(admin_only),
                    _encode_params(extra_body), _encode_params(extra_headers),
                    analysis_model, mapping_model,
                ),
            )
            await db.commit()

        # Invalidate any cached OpenAI client built from a previous version of this
        # preset, so the next request rebuilds with current base_url/api_key.
        # Best-effort: never block the upsert on cache invalidation errors.
        try:
            from src.llm import protocol_generator
            protocol_generator.invalidate_cache_for_base_url(base_url)
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

        async with self._db.connect() as db:
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
        async with self._db.connect() as db:
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
                api_key=preset.api_key,
                extra_body=preset.extra_body,
                extra_headers=preset.extra_headers,
                analysis_model=preset.analysis_model,
                mapping_model=preset.mapping_model,
            )
            count += 1

        if count:
            logger.info(f"Synced {count} model preset(s) from config")

        return count
