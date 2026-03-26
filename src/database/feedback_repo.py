"""Feedback data access."""
import aiosqlite
from typing import List, Dict, Optional, Any


class FeedbackRepository:
    """Repository for feedback operations."""

    def __init__(self, database):
        self._db = database

    async def save_feedback(self, user_id: int, rating: int, feedback_type: str,
                            comment: Optional[str] = None, protocol_id: Optional[str] = None,
                            processing_time: Optional[float] = None, file_format: Optional[str] = None,
                            file_size: Optional[int] = None) -> None:
        """Save user feedback."""
        async with aiosqlite.connect(self._db.db_path) as db:
            await db.execute("""
                INSERT INTO feedback
                (user_id, rating, feedback_type, comment, protocol_id, processing_time, file_format, file_size)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, rating, feedback_type, comment, protocol_id, processing_time, file_format, file_size))
            await db.commit()

    async def get_all_feedback(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get all feedback entries."""
        async with aiosqlite.connect(self._db.db_path) as db:
            db.row_factory = aiosqlite.Row
            query = "SELECT * FROM feedback ORDER BY created_at DESC"
            if limit:
                query += f" LIMIT {limit}"
            cursor = await db.execute(query)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_feedback_stats(self) -> Dict[str, Any]:
        """Get feedback statistics."""
        async with aiosqlite.connect(self._db.db_path) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT
                    COUNT(*) as total,
                    AVG(rating) as average_rating
                FROM feedback
            """)
            stats = await cursor.fetchone()

            cursor = await db.execute("""
                SELECT
                    feedback_type,
                    COUNT(*) as count,
                    AVG(rating) as average_rating
                FROM feedback
                GROUP BY feedback_type
            """)
            by_type = await cursor.fetchall()

            return {
                "total": stats['total'] if stats else 0,
                "average_rating": round(stats['average_rating'], 2) if stats and stats['average_rating'] else 0,
                "by_type": {row['feedback_type']: {"count": row['count'], "average_rating": round(row['average_rating'], 2)}
                            for row in by_type}
            }
