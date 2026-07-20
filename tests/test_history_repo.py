"""Характеризация HistoryRepository: история обработки и статистика пользователя (#26, #29).

Эталон поведения — методы монолита Database (save_processing_result, get_user_stats).
"""
import pytest


@pytest.fixture
async def history_repo(test_db):
    from src.database.history_repo import HistoryRepository
    return HistoryRepository(test_db)


async def test_stats_for_unknown_user_is_none(history_repo):
    assert await history_repo.get_user_stats(telegram_id=999111) is None


async def test_stats_for_user_without_history(history_repo, user_repo):
    await user_repo.create_user(telegram_id=555, username="empty")

    stats = await history_repo.get_user_stats(telegram_id=555)

    assert stats["total_files"] == 0
    assert stats["active_days"] == 0
    assert stats["first_file_date"] is None
    assert stats["last_file_date"] is None
    assert stats["llm_providers"] == []
    assert stats["favorite_templates"] == []
    assert stats["daily_activity"] == []


async def test_saved_results_feed_user_stats(history_repo, user_repo, template_repo):
    user_id = await user_repo.create_user(telegram_id=777, username="worker")
    template_id = await template_repo.create_template(name="Стандартный", content="{{plot}}")

    await history_repo.save_processing_result(
        user_id=user_id, file_name="встреча1.mp3", template_id=template_id,
        llm_provider="openai", transcription_text="текст 1", result_text="протокол 1",
    )
    await history_repo.save_processing_result(
        user_id=user_id, file_name="встреча2.mp3", template_id=template_id,
        llm_provider="openai", transcription_text="текст 2", result_text="протокол 2",
    )

    stats = await history_repo.get_user_stats(telegram_id=777)

    assert stats["total_files"] == 2
    assert stats["active_days"] == 1
    assert stats["first_file_date"] is not None
    assert stats["last_file_date"] is not None
    assert stats["llm_providers"] == [{"llm_provider": "openai", "count": 2}]
    assert stats["favorite_templates"] == [
        {"id": template_id, "name": "Стандартный", "count": 2}
    ]
    assert len(stats["daily_activity"]) == 1
    assert stats["daily_activity"][0]["count"] == 2


async def test_saved_mapping_and_type_round_trip(history_repo, user_repo, template_repo):
    """Сопоставление спикеров и тип встречи переживают запись/чтение.

    speaker_mapping хранится JSON-строкой (ensure_ascii=False), meeting_type —
    как есть. По ним перегенерация пропускает ЭТАП 1 анализа.
    """
    import json

    user_id = await user_repo.create_user(telegram_id=2024, username="keeper")
    template_id = await template_repo.create_template(name="Дейли", content="c")

    history_id = await history_repo.save_processing_result(
        user_id=user_id, file_name="m.mp3", template_id=template_id,
        llm_provider="openai", transcription_text="т", result_text="р",
        speaker_mapping={"SPEAKER_00": "Иван Петров"}, meeting_type="daily",
    )

    row = await history_repo.get_result_for_user(history_id, telegram_id=2024)

    assert row["meeting_type"] == "daily"
    assert json.loads(row["speaker_mapping"]) == {"SPEAKER_00": "Иван Петров"}


async def test_saved_result_without_mapping_stores_null(history_repo, user_repo, template_repo):
    """Пустое сопоставление — NULL, а не строка «null» или «{}»."""
    user_id = await user_repo.create_user(telegram_id=2025, username="plain")
    template_id = await template_repo.create_template(name="Т", content="c")

    history_id = await history_repo.save_processing_result(
        user_id=user_id, file_name="m.mp3", template_id=template_id,
        llm_provider="openai", transcription_text="т", result_text="р",
    )

    row = await history_repo.get_result_for_user(history_id, telegram_id=2025)

    assert row["speaker_mapping"] is None
    assert row["meeting_type"] is None


async def test_stats_ignore_other_users_history(history_repo, user_repo, template_repo):
    await user_repo.create_user(telegram_id=1001)
    other_id = await user_repo.create_user(telegram_id=1002)
    template_id = await template_repo.create_template(name="Т", content="c")

    await history_repo.save_processing_result(
        user_id=other_id, file_name="чужое.mp3", template_id=template_id,
        llm_provider="openai", transcription_text="т", result_text="р",
    )

    stats = await history_repo.get_user_stats(telegram_id=1001)
    assert stats["total_files"] == 0
