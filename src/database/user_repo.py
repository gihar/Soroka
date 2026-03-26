"""User data access."""
import aiosqlite
from typing import Optional, Dict, Any
from loguru import logger


class UserRepository:
    """Repository for user CRUD operations."""

    def __init__(self, database):
        self._db = database

    async def get_user(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Get user by Telegram ID."""
        async with aiosqlite.connect(self._db.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM users WHERE telegram_id = ?",
                (telegram_id,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def create_user(self, telegram_id: int, username: str = None,
                          first_name: str = None, last_name: str = None) -> int:
        """Create a new user."""
        async with aiosqlite.connect(self._db.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO users (telegram_id, username, first_name, last_name)
                VALUES (?, ?, ?, ?)
            """, (telegram_id, username, first_name, last_name))
            await db.commit()
            return cursor.lastrowid

    async def update_llm_preference(self, telegram_id: int, llm_provider: Optional[str]) -> None:
        """Update user's preferred LLM provider."""
        async with aiosqlite.connect(self._db.db_path) as db:
            await db.execute(
                "UPDATE users SET preferred_llm = ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
                (llm_provider, telegram_id)
            )
            await db.commit()

    async def update_openai_model_preference(self, telegram_id: int, model_key: Optional[str]) -> None:
        """Update user's preferred OpenAI model."""
        async with aiosqlite.connect(self._db.db_path) as db:
            await db.execute(
                "UPDATE users SET preferred_openai_model_key = ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
                (model_key, telegram_id)
            )
            await db.commit()

    async def update_protocol_output_preference(self, telegram_id: int, mode: Optional[str]) -> None:
        """Update user's preferred protocol output mode."""
        async with aiosqlite.connect(self._db.db_path) as db:
            await db.execute(
                "UPDATE users SET protocol_output_mode = ?, updated_at = CURRENT_TIMESTAMP WHERE telegram_id = ?",
                (mode, telegram_id)
            )
            await db.commit()

    async def set_default_template(self, telegram_id: int, template_id: int) -> bool:
        """Set default template for user."""
        async with aiosqlite.connect(self._db.db_path) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
            user_row = await cursor.fetchone()
            if not user_row:
                return False

            user_id = user_row['id']

            if template_id != 0:
                template_cursor = await db.execute("""
                    SELECT id, created_by, is_default
                    FROM templates
                    WHERE id = ?
                """, (template_id,))
                template_row = await template_cursor.fetchone()

                if not template_row:
                    return False

                template_owner = template_row["created_by"]
                is_system_template = bool(template_row["is_default"])

                owner_matches_user = template_owner == user_id
                owner_matches_telegram = template_owner == telegram_id
                owner_unknown = template_owner is None

                if not (is_system_template or owner_matches_user or owner_unknown or owner_matches_telegram):
                    return False

                if owner_matches_telegram:
                    await db.execute(
                        "UPDATE templates SET created_by = ? WHERE id = ?",
                        (user_id, template_id)
                    )

            await db.execute("""
                UPDATE users SET default_template_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE telegram_id = ?
            """, (template_id, telegram_id))

            await db.commit()
            return True

    async def reset_default_template(self, telegram_id: int) -> bool:
        """Reset user's default template to NULL."""
        async with aiosqlite.connect(self._db.db_path) as db:
            cursor = await db.execute("""
                UPDATE users SET default_template_id = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE telegram_id = ?
            """, (telegram_id,))
            await db.commit()
            return cursor.rowcount > 0

    async def get_user_stats(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Get user statistics."""
        async with aiosqlite.connect(self._db.db_path) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
            user_row = await cursor.fetchone()
            if not user_row:
                return None

            user_id = user_row['id']

            cursor = await db.execute("""
                SELECT
                    COUNT(*) as total_files,
                    COUNT(DISTINCT DATE(created_at)) as active_days,
                    MIN(created_at) as first_file_date,
                    MAX(created_at) as last_file_date
                FROM processing_history
                WHERE user_id = ?
            """, (user_id,))
            stats_row = await cursor.fetchone()

            cursor = await db.execute("""
                SELECT llm_provider, COUNT(*) as count
                FROM processing_history
                WHERE user_id = ? AND llm_provider IS NOT NULL
                GROUP BY llm_provider
                ORDER BY count DESC
            """, (user_id,))
            llm_stats = await cursor.fetchall()

            cursor = await db.execute("""
                SELECT t.id, t.name, COUNT(*) as count
                FROM processing_history ph
                JOIN templates t ON ph.template_id = t.id
                WHERE ph.user_id = ?
                GROUP BY t.id, t.name
                ORDER BY count DESC
                LIMIT 5
            """, (user_id,))
            template_stats = await cursor.fetchall()

            cursor = await db.execute("""
                SELECT DATE(created_at) as date, COUNT(*) as count
                FROM processing_history
                WHERE user_id = ? AND created_at >= DATE('now', '-30 days')
                GROUP BY DATE(created_at)
                ORDER BY date DESC
                LIMIT 30
            """, (user_id,))
            daily_activity = await cursor.fetchall()

            return {
                "total_files": stats_row['total_files'] if stats_row else 0,
                "active_days": stats_row['active_days'] if stats_row else 0,
                "first_file_date": stats_row['first_file_date'] if stats_row else None,
                "last_file_date": stats_row['last_file_date'] if stats_row else None,
                "llm_providers": [dict(row) for row in llm_stats],
                "favorite_templates": [dict(row) for row in template_stats],
                "daily_activity": [dict(row) for row in daily_activity]
            }

    async def update_saved_participants(self, telegram_id: int, participants_json: str) -> bool:
        """Update saved participants list for user."""
        try:
            async with aiosqlite.connect(self._db.db_path) as db:
                cursor = await db.execute("PRAGMA table_info(users)")
                columns = await cursor.fetchall()
                column_names = [col[1] for col in columns]

                if 'saved_participants' not in column_names:
                    logger.info("Adding saved_participants column to users table")
                    await db.execute("ALTER TABLE users ADD COLUMN saved_participants TEXT")
                    await db.commit()

                await db.execute("""
                    UPDATE users
                    SET saved_participants = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE telegram_id = ?
                """, (participants_json, telegram_id))
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Error updating participants list: {e}")
            return False
