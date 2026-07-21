"""Когда обработка встаёт на ПАУЗУ для подтверждения сопоставления, воркер не должен
'завершать' прогресс-трекер (иначе появляется ложное «Обработка завершена! Протокол
готов и будет отправлен ниже» ещё ДО подтверждения)."""

import os
import sys
from types import SimpleNamespace

import pytest

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "src"))


@pytest.mark.asyncio
async def test_paused_task_does_not_complete_tracker(monkeypatch):
    import src.services.processing_service as ps_mod
    import src.ux.progress_tracker as pt_mod
    from src.services.task_queue_manager import TaskQueueManager

    completed = []

    tracker = SimpleNamespace(current_stage=None)

    async def fake_complete_all():
        completed.append(True)

    tracker.complete_all = fake_complete_all

    async def fake_create(*a, **k):
        return tracker

    monkeypatch.setattr(
        pt_mod.ProgressFactory, "create_file_processing_tracker", fake_create
    )

    class FakeService:
        async def process_file(self, request, progress_tracker, task_id=None):
            return None  # пауза для подтверждения сопоставления

    monkeypatch.setattr(ps_mod, "ProcessingService", FakeService)

    manager = TaskQueueManager.__new__(TaskQueueManager)
    manager.bot = SimpleNamespace()
    manager.tasks = {}

    task = SimpleNamespace(
        task_id="t1", chat_id=1, message_id=None, request=SimpleNamespace()
    )

    await manager._process_task(task)

    assert completed == [], "на паузе трекер не должен завершаться (нет ложного 'Протокол готов')"


@pytest.mark.asyncio
async def test_completed_task_still_completes_tracker(monkeypatch):
    """Контроль: при НЕ-паузе (обычное завершение) трекер всё ещё завершается."""
    import src.services.processing_service as ps_mod
    import src.ux.progress_tracker as pt_mod
    from src.services.task_queue_manager import TaskQueueManager

    completed = []

    tracker = SimpleNamespace(current_stage=None)

    async def fake_complete_all():
        completed.append(True)

    tracker.complete_all = fake_complete_all

    async def fake_create(*a, **k):
        return tracker

    monkeypatch.setattr(
        pt_mod.ProgressFactory, "create_file_processing_tracker", fake_create
    )

    class FakeService:
        async def process_file(self, request, progress_tracker, task_id=None):
            # Обычный результат (не пауза). Доставку и статус задачи проставляет
            # единый хвост ВНУТРИ process_file (ADR-0003) — воркер их не трогает.
            return SimpleNamespace()

    monkeypatch.setattr(ps_mod, "ProcessingService", FakeService)

    manager = TaskQueueManager.__new__(TaskQueueManager)
    manager.bot = SimpleNamespace()
    manager.tasks = {}

    task = SimpleNamespace(
        task_id="t2", chat_id=1, message_id=None, request=SimpleNamespace()
    )

    await manager._process_task(task)

    assert completed == [True], "при обычном завершении трекер должен завершаться"
