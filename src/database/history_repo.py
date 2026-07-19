"""История обработки: свершившиеся результаты и статистика пользователя."""
from typing import Any, Dict, Optional


class HistoryRepository:
    """Repository for processing history: saved results and user stats."""

    def __init__(self, database):
        self._db = database

    async def save_processing_result(self, user_id: int, file_name: str, template_id: int,
                                     llm_provider: str, transcription_text: str,
                                     result_text: str) -> Optional[int]:
        """Save processing result to history. Returns the new row id."""
        async with self._db.connect() as db:
            cursor = await db.execute("""
                INSERT INTO processing_history
                (user_id, file_name, template_id, llm_provider, transcription_text, result_text)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, file_name, template_id, llm_provider, transcription_text, result_text))
            await db.commit()
            return cursor.lastrowid

    async def get_result_for_user(self, history_id: int, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Запись истории по id — только если принадлежит пользователю Telegram.

        Проверка владельца обязательна: history_id приходит из callback_data,
        которую может прислать кто угодно.
        """
        async with self._db.connect() as db:
            cursor = await db.execute("""
                SELECT ph.id, ph.user_id, ph.file_name, ph.template_id,
                       ph.llm_provider, ph.transcription_text, ph.result_text
                FROM processing_history ph
                JOIN users u ON ph.user_id = u.id
                WHERE ph.id = ? AND u.telegram_id = ?
            """, (history_id, telegram_id))
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_user_stats(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Get user statistics computed from processing history."""
        async with self._db.connect() as db:
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
