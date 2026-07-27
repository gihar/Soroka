"""Трекер прогресса не должен переживать завершённую обработку.

Прод 27.07.2026, трижды за сутки (06:20, 11:26, 13:07):

    ⚠️ Трекер превысил максимальное время жизни (1800с / 30мин).
       Принудительное завершение.

Разбор первого случая: обработка успешно завершилась в 05:52:43
(``continue_processing_after_mapping_confirmation:624``), а гард добил трекер в
06:20:31 — через 27 мин 48 с. Всё это время ``_auto_update`` продолжал
редактировать сообщение прогресса под уже доставленным протоколом.

Путь возобновления после подтверждения сопоставления создаёт СВОЙ трекер, а
``complete_all()`` живёт только в воркере (и там намеренно пропускается при
``paused``) и в ветке кеш-хита. ``result_sender`` трогает трекер лишь в
``except``. На happy path возобновления его не закрывает никто.

Существующие тесты этого пути подменяют фабрику трекера на
``SimpleNamespace(start_stage=AsyncMock())`` — без реального ``_auto_update``
утечка структурно невидима. Здесь трекер настоящий, заглушён только вывод в
Telegram.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from loguru import logger

from src.models.processing import ProcessingRequest, TranscriptionResult
from src.services.mapping_session import MappingSession
from src.ux.progress_tracker import ProgressTracker


def _real_tracker() -> ProgressTracker:
    """Настоящий трекер с живым asyncio-циклом, но без выхода в Telegram."""
    tracker = ProgressTracker(
        bot=SimpleNamespace(), chat_id=1, message=SimpleNamespace(message_id=10)
    )
    tracker.setup_default_stages()
    tracker.update_display = AsyncMock()  # единственная заглушка — вывод
    return tracker


def _resume_session() -> MappingSession:
    return MappingSession(
        request=ProcessingRequest(
            file_name="meeting.mp3", llm_provider="openai", user_id=1, template_id=5
        ),
        transcription_result=TranscriptionResult(transcription="расшифровка"),
        speaker_mapping={},
        meeting_type="daily",
        temp_file_path=None,
        cache_key=None,
        task_id=None,
        metrics=SimpleNamespace(llm_duration=0.0, protocol_quality_score=0.0),
        template=SimpleNamespace(id=5, name="Дейли", content="# {{ meeting_title }}"),
    )


def _stub_resume_deps(service) -> None:
    service.llm_gen = SimpleNamespace(
        optimized_llm_generation=AsyncMock(return_value={"meeting_title": "Планёрка"}),
        resolve_model_display_name=AsyncMock(return_value="GPT"),
    )
    service.formatter = SimpleNamespace(format_protocol=lambda *a, **k: "# Протокол")
    service.history = SimpleNamespace(
        save_processing_history=AsyncMock(return_value=99),
        cleanup_temp_file=AsyncMock(),
    )


async def test_leaked_tracker_is_what_logs_the_lifetime_warning():
    """Незакрытый трекер действительно выдаёт ту самую строку прода.

    Связывает симптом с механизмом: пока ``current_stage`` не снят, цикл жив и
    рано или поздно упирается в гард. Лимит сжат до нуля, чтобы не ждать 30 минут.
    """
    tracker = _real_tracker()
    tracker._max_lifetime_seconds = 0

    messages = []
    sink_id = logger.add(lambda m: messages.append(m.record["message"]), level="WARNING")
    try:
        await tracker.start_stage("analysis")
        await asyncio.wait_for(tracker.update_task, timeout=5)
    finally:
        logger.remove(sink_id)

    assert any("превысил максимальное время жизни" in m for m in messages), messages


async def test_stall_guard_stops_tracker_stuck_on_one_stage():
    """Второй рубеж: этап, не двигающийся дольше лимита, глушит цикл сам.

    Гард на 1800с — слишком поздний рубеж: он позволяет ~350 лишних правок
    сообщения. Порог этапа выбран по проду: самый длинный реальный «Анализ» шёл
    374с (16:17:37 → 16:23:51), отсюда 600с — с запасом ×1.6 и без ложных
    срабатываний на живой работе.
    """
    tracker = _real_tracker()
    tracker._max_stage_seconds = 0  # сжато, чтобы не ждать 10 минут

    messages = []
    sink_id = logger.add(lambda m: messages.append(m.record["message"]), level="WARNING")
    try:
        await tracker.start_stage("analysis")
        await asyncio.wait_for(tracker.update_task, timeout=5)
    finally:
        logger.remove(sink_id)

    assert any("этап не двигается" in m.lower() for m in messages), messages


async def test_complete_all_is_idempotent():
    """Хвост и finally воркера оба закрывают трекер — второй раз должен быть тих.

    Без идемпотентности повторный complete_all() шлёт ещё одну правку «Протокол
    готов» в Telegram: лишний вызов API и мигание сообщения.
    """
    tracker = _real_tracker()
    await tracker.start_stage("analysis")

    await tracker.complete_all()
    edits_after_first = tracker.update_display.await_count

    await tracker.complete_all()

    assert tracker.update_display.await_count == edits_after_first, (
        "повторный complete_all() не должен трогать сообщение"
    )
    assert tracker.update_task is None


async def test_tail_closes_tracker_even_when_delivery_fails(monkeypatch):
    """Доставка упала — трекер всё равно закрыт: гасить его в finally, не после.

    Иначе исключение доставки оставляло бы цикл живым на те же 28 минут.
    """
    import src.services.processing.completion as completion

    tracker = _real_tracker()
    await tracker.start_stage("analysis")

    monkeypatch.setattr(completion.queue_repo, "update_queue_task_status", AsyncMock())

    async def boom(_result):
        raise RuntimeError("Telegram недоступен")

    deps = SimpleNamespace(
        history=SimpleNamespace(save_processing_history=AsyncMock(return_value=1)),
    )

    with pytest.raises(RuntimeError):
        await completion._record_and_deliver(
            SimpleNamespace(history_id=None),
            request=SimpleNamespace(), deps=deps, delivery=boom,
            task_id=None, progress_tracker=tracker,
        )

    assert tracker.update_task is None, "трекер должен быть закрыт и на исключении"


async def test_resume_does_not_leave_autoupdate_running(monkeypatch):
    """Ядро регрессии: после успешного возобновления цикл трекера не жив.

    Красный до фикса — ровно та утечка, которую гард добивал через 28 минут.
    """
    import src.services.processing.completion as completion
    import src.services.processing.processing_service as pss
    import src.services.result_sender as rs
    import src.ux.progress_tracker as pt_mod

    service = pss.ProcessingService.__new__(pss.ProcessingService)
    _stub_resume_deps(service)

    tracker = _real_tracker()
    monkeypatch.setattr(
        pt_mod.ProgressFactory,
        "create_file_processing_tracker",
        AsyncMock(return_value=tracker),
    )
    monkeypatch.setattr(
        completion, "performance_cache", SimpleNamespace(set=AsyncMock())
    )
    monkeypatch.setattr(completion.queue_repo, "update_queue_task_status", AsyncMock())
    monkeypatch.setattr(rs, "send_result_to_user", AsyncMock(return_value=True))
    # Автообновление не должно уходить в сеть, если цикл всё же жив.
    monkeypatch.setattr(
        pt_mod.telegram_rate_limiter.flood_control,
        "is_blocked",
        AsyncMock(return_value=(False, 0)),
    )

    task_after = None
    try:
        await service.continue_processing_after_mapping_confirmation(
            session=_resume_session(), confirmed_mapping={},
            bot=SimpleNamespace(), chat_id=1,
        )
        await asyncio.sleep(0)  # даём отменённой задаче шанс дойти до финала

        task_after = tracker.update_task
        alive = task_after is not None and not task_after.done()
        assert not alive, (
            "цикл автообновления остался жив после завершения обработки — "
            "он будет редактировать сообщение прогресса до гарда в 1800с"
        )
        assert tracker.current_stage is None, (
            "этап не снят: _auto_update продолжит крутиться по условию while"
        )
    finally:
        # Тест остаётся гигиеничным и когда он красный: висящая задача снимается.
        # _auto_update глотает CancelledError сам, поэтому await не обязан бросать.
        if task_after is not None and not task_after.done():
            task_after.cancel()
            try:
                await task_after
            except asyncio.CancelledError:
                pass
