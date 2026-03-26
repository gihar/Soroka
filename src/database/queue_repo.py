"""Task queue data access."""
import aiosqlite
from typing import List, Dict, Optional, Any
from loguru import logger


class QueueRepository:
    """Repository for task queue operations."""

    def __init__(self, database):
        self._db = database

    async def save_queue_task(self, task_data: Dict[str, Any]) -> bool:
        """Save a task to the queue."""
        try:
            async with aiosqlite.connect(self._db.db_path) as db:
                await db.execute("""
                    INSERT INTO queue_tasks (
                        task_id, user_id, chat_id, message_id,
                        file_id, file_path, file_name, template_id,
                        llm_provider, language, is_external_file,
                        status, priority, created_at, started_at, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    task_data['task_id'],
                    task_data['user_id'],
                    task_data['chat_id'],
                    task_data.get('message_id'),
                    task_data.get('file_id'),
                    task_data.get('file_path'),
                    task_data['file_name'],
                    task_data['template_id'],
                    task_data['llm_provider'],
                    task_data.get('language', 'ru'),
                    task_data.get('is_external_file', False),
                    task_data['status'],
                    task_data.get('priority', 1),
                    task_data['created_at'],
                    task_data.get('started_at'),
                    task_data.get('error_message')
                ))
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Error saving queue task to DB: {e}")
            return False

    async def update_queue_task_status(self, task_id: str, status: str,
                                       started_at: Optional[str] = None,
                                       error_message: Optional[str] = None) -> bool:
        """Update task status in queue."""
        try:
            async with aiosqlite.connect(self._db.db_path) as db:
                if started_at:
                    await db.execute("""
                        UPDATE queue_tasks
                        SET status = ?, started_at = ?, error_message = ?
                        WHERE task_id = ?
                    """, (status, started_at, error_message, task_id))
                else:
                    await db.execute("""
                        UPDATE queue_tasks
                        SET status = ?, error_message = ?
                        WHERE task_id = ?
                    """, (status, error_message, task_id))
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Error updating task status: {e}")
            return False

    async def update_queue_task_message_id(self, task_id: str, message_id: int) -> bool:
        """Update message_id for a task."""
        try:
            async with aiosqlite.connect(self._db.db_path) as db:
                await db.execute("""
                    UPDATE queue_tasks
                    SET message_id = ?
                    WHERE task_id = ?
                """, (message_id, task_id))
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Error updating task message_id: {e}")
            return False

    async def get_pending_queue_tasks(self) -> List[Dict[str, Any]]:
        """Get all queued tasks sorted by priority and creation time."""
        async with aiosqlite.connect(self._db.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT * FROM queue_tasks
                WHERE status = 'queued'
                ORDER BY priority DESC, created_at ASC
            """)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def cleanup_completed_queue_tasks(self, hours: int = 24) -> int:
        """Clean up completed tasks older than N hours."""
        try:
            async with aiosqlite.connect(self._db.db_path) as db:
                cursor = await db.execute("""
                    DELETE FROM queue_tasks
                    WHERE status IN ('completed', 'cancelled', 'failed')
                    AND created_at < DATETIME('now', ?)
                """, (f'-{hours} hours',))
                await db.commit()
                return cursor.rowcount
        except Exception as e:
            logger.error(f"Error cleaning up completed tasks: {e}")
            return 0

    async def save_processing_result(self, user_id: int, file_name: str, template_id: int,
                                     llm_provider: str, transcription_text: str, result_text: str) -> None:
        """Save processing result to history."""
        async with aiosqlite.connect(self._db.db_path) as db:
            await db.execute("""
                INSERT INTO processing_history
                (user_id, file_name, template_id, llm_provider, transcription_text, result_text)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, file_name, template_id, llm_provider, transcription_text, result_text))
            await db.commit()
