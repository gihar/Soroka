"""Реестр callbacks OOM-защиты не должен удерживать владельцев (#прод-утечка).

Прод-инцидент 2026-07-30: `TranscriptionService` создаётся на каждую задачу
(`task_queue_manager` → `ProcessingService` → `BaseProcessingService`), а его
конструктор клал связанный метод `self._cleanup_models` в список глобального
синглтона `OOMProtection`. Список держал жёсткую ссылку → ни один экземпляр не
собирался GC, три модели Whisper висели в RAM, система вставала на 91%.

Канон: связанный метод регистрируется слабо (владелец умер — запись исчезла),
обычная функция/замыкание — жёстко (её больше некому держать).
"""
import gc

from src.performance.callback_registry import CallbackRegistry


class Owner:
    """Владелец связанного метода — аналог TranscriptionService."""

    def __init__(self, log):
        self.log = log

    def on_cleanup(self, cleanup_type="soft"):
        self.log.append((id(self), cleanup_type))


def test_bound_method_does_not_pin_owner():
    registry = CallbackRegistry()
    owner = Owner([])
    registry.add(owner.on_cleanup)

    del owner
    gc.collect()

    assert registry.callbacks() == []


def test_dead_owner_is_pruned_from_registry():
    registry = CallbackRegistry()
    alive_log = []
    alive = Owner(alive_log)
    doomed = Owner([])

    registry.add(alive.on_cleanup)
    registry.add(doomed.on_cleanup)
    del doomed
    gc.collect()

    registry.invoke("aggressive")

    assert len(registry) == 1
    assert alive_log == [(id(alive), "aggressive")]


def test_live_bound_method_is_invoked():
    registry = CallbackRegistry()
    log = []
    owner = Owner(log)
    registry.add(owner.on_cleanup)

    registry.invoke("soft")

    assert log == [(id(owner), "soft")]


def test_plain_function_is_held_strongly():
    """Замыкание регистрируют один раз на старте — слабая ссылка убила бы его."""
    registry = CallbackRegistry()
    log = []

    def closure_callback(cleanup_type):
        log.append(cleanup_type)

    registry.add(closure_callback)
    del closure_callback
    gc.collect()

    registry.invoke("aggressive")

    assert log == ["aggressive"]


def test_no_arg_callbacks_are_supported():
    """warning/critical callbacks вызываются без аргументов."""
    registry = CallbackRegistry()
    log = []
    registry.add(lambda: log.append("warned"))

    registry.invoke()

    assert log == ["warned"]


def test_duplicate_registration_is_ignored():
    """Повторное создание сервиса не должно множить один и тот же callback."""
    registry = CallbackRegistry()
    log = []
    owner = Owner(log)

    registry.add(owner.on_cleanup)
    registry.add(owner.on_cleanup)

    assert len(registry) == 1
    registry.invoke("soft")
    assert log == [(id(owner), "soft")]


def test_failing_callback_does_not_block_others():
    registry = CallbackRegistry()
    log = []

    def boom(cleanup_type):
        raise RuntimeError("callback упал")

    registry.add(boom)
    registry.add(lambda cleanup_type: log.append(cleanup_type))

    registry.invoke("aggressive")

    assert log == ["aggressive"]


def test_slots_owner_falls_back_to_strong_ref():
    """Без __weakref__ слабую ссылку не сделать — защита важнее экономии."""

    class SlotsOwner:
        __slots__ = ("log",)

        def __init__(self, log):
            self.log = log

        def on_cleanup(self, cleanup_type):
            self.log.append(cleanup_type)

    registry = CallbackRegistry()
    log = []
    registry.add(SlotsOwner(log).on_cleanup)

    gc.collect()
    registry.invoke("aggressive")

    assert log == ["aggressive"]


def test_remove_unregisters_callback():
    registry = CallbackRegistry()
    log = []
    owner = Owner(log)
    registry.add(owner.on_cleanup)

    registry.remove(owner.on_cleanup)
    registry.invoke("soft")

    assert len(registry) == 0
    assert log == []
