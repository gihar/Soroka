"""Реестр callbacks, не удерживающий владельцев.

Глобальный синглтон OOM-защиты живёт всё время работы бота, а сервисы,
которые на него подписываются, создаются на каждую задачу. Жёсткая ссылка на
связанный метод пиновала бы такой сервис навсегда вместе с загруженными
моделями — это и был прод-инцидент 2026-07-30.

Правило: связанный метод храним слабо (умер владелец — запись выпала), любую
другую функцию — жёстко, потому что замыкания и лямбды регистрируют один раз
на старте и держать их больше некому.
"""
import weakref
from typing import Callable, List

from loguru import logger


def _is_bound_method(callback: Callable) -> bool:
    return hasattr(callback, "__self__") and callback.__self__ is not None


class CallbackRegistry:
    """Список callbacks со слабыми ссылками на связанные методы."""

    def __init__(self, name: str = "callbacks"):
        self._name = name
        self._weak: List[weakref.WeakMethod] = []
        self._strong: List[Callable] = []

    def add(self, callback: Callable) -> None:
        """Зарегистрировать callback; повторная регистрация игнорируется."""
        if _is_bound_method(callback):
            self._prune()
            if any(ref() == callback for ref in self._weak):
                return
            try:
                self._weak.append(weakref.WeakMethod(callback))
                return
            except TypeError:
                # Владелец без __weakref__ (например, __slots__) — слабую
                # ссылку не сделать; держим жёстко, чтобы не потерять защиту
                logger.warning(
                    f"{self._name}: владелец {type(callback.__self__).__name__} "
                    "не поддерживает слабые ссылки, callback удерживается жёстко"
                )

        if callback not in self._strong:
            self._strong.append(callback)

    def remove(self, callback: Callable) -> None:
        """Снять callback с регистрации; отсутствующий — не ошибка."""
        if _is_bound_method(callback):
            self._weak = [ref for ref in self._weak if ref() not in (None, callback)]
            return

        self._strong = [item for item in self._strong if item != callback]

    def callbacks(self) -> List[Callable]:
        """Живые callbacks; мёртвые владельцы попутно вычищаются."""
        self._prune()
        resolved = [ref() for ref in self._weak]
        return [item for item in resolved if item is not None] + list(self._strong)

    def invoke(self, *args) -> None:
        """Вызвать все живые callbacks; падение одного не мешает остальным."""
        for callback in self.callbacks():
            try:
                callback(*args)
            except Exception as e:
                logger.error(f"Ошибка в {self._name} callback: {e}")

    def clear(self) -> None:
        self._weak = []
        self._strong = []

    def _prune(self) -> None:
        self._weak = [ref for ref in self._weak if ref() is not None]

    def __len__(self) -> int:
        return len(self.callbacks())

    def __iter__(self):
        return iter(self.callbacks())

    def __bool__(self) -> bool:
        return len(self) > 0
