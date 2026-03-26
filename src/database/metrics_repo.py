"""Processing metrics data access."""
import aiosqlite
from typing import List, Dict, Any


class MetricsRepository:
    """Repository for processing metrics operations."""

    def __init__(self, database):
        self._db = database

    async def save_processing_metric(self, metric_data: Dict[str, Any]) -> int:
        """Save a processing metric."""
        async with aiosqlite.connect(self._db.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO processing_metrics (
                    file_name, user_id, start_time, end_time,
                    download_duration, validation_duration, conversion_duration,
                    transcription_duration, diarization_duration, llm_duration, formatting_duration,
                    file_size_bytes, file_format, audio_duration_seconds,
                    transcription_length, speakers_count,
                    error_occurred, error_stage, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                metric_data.get('file_name'),
                metric_data.get('user_id'),
                metric_data.get('start_time'),
                metric_data.get('end_time'),
                metric_data.get('download_duration', 0.0),
                metric_data.get('validation_duration', 0.0),
                metric_data.get('conversion_duration', 0.0),
                metric_data.get('transcription_duration', 0.0),
                metric_data.get('diarization_duration', 0.0),
                metric_data.get('llm_duration', 0.0),
                metric_data.get('formatting_duration', 0.0),
                metric_data.get('file_size_bytes', 0),
                metric_data.get('file_format'),
                metric_data.get('audio_duration_seconds', 0.0),
                metric_data.get('transcription_length', 0),
                metric_data.get('speakers_count', 0),
                metric_data.get('error_occurred', False),
                metric_data.get('error_stage'),
                metric_data.get('error_message')
            ))
            await db.commit()
            return cursor.lastrowid

    async def get_processing_metrics(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Get processing metrics for the last N hours."""
        async with aiosqlite.connect(self._db.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT * FROM processing_metrics
                WHERE created_at >= DATETIME('now', ?)
                ORDER BY created_at DESC
            """, (f'-{hours} hours',))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
