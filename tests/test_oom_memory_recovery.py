"""OOM-защита обязана пробовать освободить память до отказа (#прод-дедлок).

Прод-инцидент 2026-07-30: `can_process_file` отклоняла файл при >= 90% и просто
возвращала False, а `_cleanup_models("aggressive")` (единственное, что выгружает
Whisper) запускалась только при >= 95%. В коридоре 90–95% бот отказывал всем и
никогда не чистился: 27 отказов подряд, 0 агрессивных очисток, 0 транскрипций.

Канон: перед отказом по памяти — агрессивная очистка и перепроверка.
"""
from unittest.mock import patch

import pytest

from src.performance.oom_protection import MemoryLimits, OOMProtection


class FakeMemory:
    """Виртуальная память с управляемой последовательностью замеров."""

    def __init__(self, total_mb, percents, available_mb):
        self.total = total_mb * 1024 * 1024
        self._percents = list(percents)
        self._available_mb = available_mb
        self.reads = 0

    def __call__(self):
        percent = self._percents[min(self.reads, len(self._percents) - 1)]
        self.reads += 1
        available = self._available_mb[min(self.reads - 1, len(self._available_mb) - 1)]
        return type(
            "VM",
            (),
            {
                "total": self.total,
                "available": available * 1024 * 1024,
                "used": self.total - available * 1024 * 1024,
                "percent": percent,
            },
        )()


@pytest.fixture
def limits():
    return MemoryLimits(
        max_file_size_mb=100.0,
        max_memory_usage_percent=90.0,
        critical_memory_percent=95.0,
        min_available_memory_mb=200.0,
    )


def _protection(limits, memory):
    with patch("src.performance.oom_protection.psutil.virtual_memory", memory):
        protection = OOMProtection(limits=limits)
    return protection


def test_cleanup_runs_before_refusing_on_high_memory(limits):
    """91% → чистка выгрузила модели → 60% → файл принимается."""
    memory = FakeMemory(4000, [91.0, 91.0, 60.0, 60.0], [300, 300, 1600, 1600])
    protection = _protection(limits, memory)
    freed = []
    protection.add_cleanup_callback(lambda cleanup_type: freed.append(cleanup_type))

    with patch("src.performance.oom_protection.psutil.virtual_memory", memory):
        can_process, reason = protection.can_process_file(10.0)

    assert "aggressive" in freed
    assert can_process, reason


def test_refuses_when_cleanup_does_not_help(limits):
    """Чистка не помогла — отказ остаётся, но попытка была."""
    memory = FakeMemory(4000, [91.0], [300])
    protection = _protection(limits, memory)
    freed = []
    protection.add_cleanup_callback(lambda cleanup_type: freed.append(cleanup_type))

    with patch("src.performance.oom_protection.psutil.virtual_memory", memory):
        can_process, reason = protection.can_process_file(10.0)

    assert "aggressive" in freed
    assert not can_process
    assert "памяти" in reason


def test_healthy_memory_does_not_trigger_cleanup(limits):
    """На здоровой памяти чистку дёргать незачем — она выгружает модели."""
    memory = FakeMemory(4000, [40.0], [2400])
    protection = _protection(limits, memory)
    freed = []
    protection.add_cleanup_callback(lambda cleanup_type: freed.append(cleanup_type))

    with patch("src.performance.oom_protection.psutil.virtual_memory", memory):
        can_process, reason = protection.can_process_file(10.0)

    assert freed == []
    assert can_process, reason


def test_oversized_file_refused_without_cleanup(limits):
    """Размер файла памятью не лечится — чистку не запускаем."""
    memory = FakeMemory(4000, [40.0], [2400])
    protection = _protection(limits, memory)
    freed = []
    protection.add_cleanup_callback(lambda cleanup_type: freed.append(cleanup_type))

    with patch("src.performance.oom_protection.psutil.virtual_memory", memory):
        can_process, reason = protection.can_process_file(500.0)

    assert freed == []
    assert not can_process
    assert "слишком большой" in reason


def test_low_available_memory_also_retries_after_cleanup(limits):
    """Порог min_available страдает тем же дедлоком — лечим и его."""
    memory = FakeMemory(4000, [88.0, 88.0, 50.0, 50.0], [150, 150, 2000, 2000])
    protection = _protection(limits, memory)
    freed = []
    protection.add_cleanup_callback(lambda cleanup_type: freed.append(cleanup_type))

    with patch("src.performance.oom_protection.psutil.virtual_memory", memory):
        can_process, reason = protection.can_process_file(10.0)

    assert "aggressive" in freed
    assert can_process, reason


def test_service_instances_do_not_accumulate_in_singleton(limits):
    """Регрессия на сам инцидент: 20 сервисов подряд — реестр не растёт."""
    memory = FakeMemory(4000, [40.0], [2400])
    protection = _protection(limits, memory)

    class Service:
        def __init__(self, prot):
            prot.add_cleanup_callback(self._cleanup)

        def _cleanup(self, cleanup_type="soft"):
            pass

    for _ in range(20):
        Service(protection)

    import gc

    gc.collect()

    assert len(protection.cleanup_callbacks) == 0
