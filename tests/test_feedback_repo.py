"""Характеризация FeedbackRepository: обратная связь (#27).

Эталон поведения — методы монолита Database (save_feedback, get_all_feedback,
get_feedback_stats).
"""
import pytest


@pytest.fixture
async def feedback_repo(test_db):
    from src.database.feedback_repo import FeedbackRepository
    return FeedbackRepository(test_db)


async def test_stats_when_no_feedback(feedback_repo):
    stats = await feedback_repo.get_feedback_stats()

    assert stats == {"total": 0, "average_rating": 0, "by_type": {}}


async def test_saved_feedback_is_returned_newest_first(feedback_repo):
    await feedback_repo.save_feedback(
        user_id=1, rating=5, feedback_type="protocol_quality",
        comment="отлично", protocol_id="p-1",
        processing_time=12.5, file_format="mp3", file_size=1024,
    )
    await feedback_repo.save_feedback(user_id=2, rating=3, feedback_type="usability")

    entries = await feedback_repo.get_all_feedback()

    assert len(entries) == 2
    first = next(e for e in entries if e["user_id"] == 1)
    assert first["rating"] == 5
    assert first["feedback_type"] == "protocol_quality"
    assert first["comment"] == "отлично"
    assert first["protocol_id"] == "p-1"
    assert first["processing_time"] == 12.5
    assert first["file_format"] == "mp3"
    assert first["file_size"] == 1024


async def test_get_all_feedback_respects_limit(feedback_repo):
    for rating in (1, 2, 3):
        await feedback_repo.save_feedback(user_id=1, rating=rating, feedback_type="usability")

    entries = await feedback_repo.get_all_feedback(limit=2)

    assert len(entries) == 2


async def test_stats_aggregate_by_type_with_rounded_averages(feedback_repo):
    await feedback_repo.save_feedback(user_id=1, rating=5, feedback_type="protocol_quality")
    await feedback_repo.save_feedback(user_id=2, rating=4, feedback_type="protocol_quality")
    await feedback_repo.save_feedback(user_id=3, rating=2, feedback_type="usability")

    stats = await feedback_repo.get_feedback_stats()

    assert stats["total"] == 3
    assert stats["average_rating"] == round((5 + 4 + 2) / 3, 2)
    assert stats["by_type"]["protocol_quality"] == {"count": 2, "average_rating": 4.5}
    assert stats["by_type"]["usability"] == {"count": 1, "average_rating": 2.0}
