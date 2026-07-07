"""Характеризация MetricsRepository: метрики обработки (#28).

Эталон поведения — методы монолита Database (save_processing_metric,
get_processing_metrics).
"""
import pytest


@pytest.fixture
async def metrics_repo(test_db):
    from src.database.metrics_repo import MetricsRepository
    return MetricsRepository(test_db)


async def test_saved_metric_is_returned_with_defaults(metrics_repo):
    metric_id = await metrics_repo.save_processing_metric({
        "file_name": "встреча.mp3",
        "user_id": 7,
        "start_time": "2026-07-07 10:00:00",
        "end_time": "2026-07-07 10:05:00",
        "transcription_duration": 42.0,
        "error_occurred": False,
    })

    assert isinstance(metric_id, int) and metric_id > 0

    metrics = await metrics_repo.get_processing_metrics(hours=24)
    assert len(metrics) == 1
    m = metrics[0]
    assert m["file_name"] == "встреча.mp3"
    assert m["user_id"] == 7
    assert m["transcription_duration"] == 42.0
    # незаданные длительности характеризуются дефолтом 0.0
    assert m["download_duration"] == 0.0
    assert m["llm_duration"] == 0.0
    assert m["error_occurred"] == 0
    assert m["error_stage"] is None


async def test_metrics_window_excludes_old_entries(metrics_repo, test_db):
    await metrics_repo.save_processing_metric({
        "file_name": "старая.mp3", "user_id": 1,
        "start_time": "2026-01-01 10:00:00",
    })
    # Состариваем запись напрямую: окно фильтрует по created_at
    async with test_db.connect() as conn:
        await conn.execute(
            "UPDATE processing_metrics SET created_at = DATETIME('now', '-48 hours')"
        )
        await conn.commit()
    await metrics_repo.save_processing_metric({
        "file_name": "свежая.mp3", "user_id": 1,
        "start_time": "2026-07-07 10:00:00",
    })

    metrics = await metrics_repo.get_processing_metrics(hours=24)

    assert [m["file_name"] for m in metrics] == ["свежая.mp3"]
