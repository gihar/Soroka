"""
Система защиты от OOM Killer
"""

import os
import gc
import psutil
import asyncio
import signal
import sys
from typing import Dict, Any, Optional, Callable
from datetime import datetime, timedelta
from loguru import logger
from dataclasses import dataclass
from contextlib import asynccontextmanager

from config import settings


@dataclass
class MemoryLimits:
    """Лимиты памяти для различных операций"""
    max_file_size_mb: float = 100.0  # Максимальный размер файла для обработки
    max_memory_usage_percent: float = 85.0  # Максимальное использование памяти
    critical_memory_percent: float = 95.0  # Критический уровень памяти
    min_available_memory_mb: float = 200.0  # Минимальная доступная память
    max_process_memory_mb: float = 1024.0  # Максимальная память процесса


DEFAULT_MEMORY_LIMITS = MemoryLimits()


class OOMProtection:
    """Система защиты от OOM Killer"""
    
    def __init__(self, limits: Optional[MemoryLimits] = None):
        if limits is None:
            max_file_size_mb = settings.oom_max_file_size_mb

            if max_file_size_mb is None:
                configured_max_bytes = settings.max_file_size
                max_file_size_mb = configured_max_bytes / (1024 * 1024)

                if max_file_size_mb <= 0:
                    max_file_size_mb = DEFAULT_MEMORY_LIMITS.max_file_size_mb

            limits = MemoryLimits(
                max_file_size_mb=max_file_size_mb,
                max_memory_usage_percent=settings.oom_max_memory_percent
            )

        self.limits = limits
        self.process = psutil.Process()
        self.system_memory = psutil.virtual_memory()
        
        # Статистика
        self.oom_events: list = []
        self.memory_warnings: list = []
        self.cleanup_events: list = []
        
        # Callbacks для уведомлений
        self.warning_callbacks: list = []
        self.critical_callbacks: list = []
        self.cleanup_callbacks: list = []
        
        # Флаг активной защиты
        self.protection_enabled = True
        
        logger.info(f"OOM Protection инициализирована: "
                   f"max_file={self.limits.max_file_size_mb}MB, "
                   f"max_memory={self.limits.max_memory_usage_percent}%")
    
    def get_memory_status(self) -> Dict[str, Any]:
        """Получить текущий статус памяти"""
        system_memory = psutil.virtual_memory()
        process_memory = self.process.memory_info()
        
        return {
            "system": {
                "total_mb": round(system_memory.total / (1024 * 1024), 2),
                "available_mb": round(system_memory.available / (1024 * 1024), 2),
                "used_mb": round(system_memory.used / (1024 * 1024), 2),
                "percent": round(system_memory.percent, 2)
            },
            "process": {
                "rss_mb": round(process_memory.rss / (1024 * 1024), 2),
                "vms_mb": round(process_memory.vms / (1024 * 1024), 2)
            },
            "limits": {
                "max_file_size_mb": self.limits.max_file_size_mb,
                "max_memory_percent": self.limits.max_memory_usage_percent,
                "critical_memory_percent": self.limits.critical_memory_percent,
                "min_available_mb": self.limits.min_available_memory_mb
            },
            "status": self._get_memory_status_level(system_memory.percent)
        }
    
    def _get_memory_status_level(self, memory_percent: float) -> str:
        """Определить уровень использования памяти"""
        if memory_percent >= self.limits.critical_memory_percent:
            return "critical"
        elif memory_percent >= self.limits.max_memory_usage_percent:
            return "warning"
        else:
            return "normal"
    
    def can_process_file(self, file_size_mb: float) -> tuple[bool, str]:
        """Проверить, можно ли обработать файл"""
        memory_status = self.get_memory_status()
        
        # Проверяем размер файла
        if file_size_mb > self.limits.max_file_size_mb:
            return False, f"Файл слишком большой: {file_size_mb:.1f}MB > {self.limits.max_file_size_mb}MB"
        
        # Проверяем доступную память
        available_mb = memory_status["system"]["available_mb"]
        if available_mb < self.limits.min_available_memory_mb:
            return False, f"Недостаточно памяти: {available_mb:.1f}MB < {self.limits.min_available_memory_mb}MB"
        
        # Проверяем использование памяти
        memory_percent = memory_status["system"]["percent"]
        if memory_percent >= self.limits.max_memory_usage_percent:
            return False, f"Высокое использование памяти: {memory_percent:.1f}% >= {self.limits.max_memory_usage_percent}%"
        
        return True, "OK"
    
    def check_memory_before_operation(self, operation_name: str, estimated_memory_mb: float = 0) -> bool:
        """Проверить память перед операцией"""
        memory_status = self.get_memory_status()
        memory_percent = memory_status["system"]["percent"]
        
        # Проверяем критический уровень
        if memory_percent >= self.limits.critical_memory_percent:
            logger.critical(f"Критический уровень памяти перед {operation_name}: {memory_percent:.1f}%")
            self._trigger_critical_cleanup()
            return False
        
        # Проверяем предупреждение
        if memory_percent >= self.limits.max_memory_usage_percent:
            logger.warning(f"Высокий уровень памяти перед {operation_name}: {memory_percent:.1f}%")
            self._trigger_warning_cleanup()
        
        # Проверяем, хватит ли памяти для операции
        if estimated_memory_mb > 0:
            available_mb = memory_status["system"]["available_mb"]
            if available_mb < estimated_memory_mb + self.limits.min_available_memory_mb:
                logger.warning(f"Недостаточно памяти для {operation_name}: "
                             f"нужно {estimated_memory_mb}MB, доступно {available_mb}MB")
                self._trigger_warning_cleanup()
                return False
        
        return True
    
    def _trigger_warning_cleanup(self):
        """Запустить очистку при предупреждении"""
        logger.info("Запуск очистки памяти при предупреждении")
        
        # Запускаем callbacks
        for callback in self.warning_callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"Ошибка в warning callback: {e}")
        
        # Мягкая очистка
        self._soft_cleanup()
        
        # Записываем событие
        self.memory_warnings.append({
            "timestamp": datetime.now(),
            "type": "warning_cleanup",
            "memory_status": self.get_memory_status()
        })
    
    def _trigger_critical_cleanup(self):
        """Запустить критическую очистку"""
        logger.critical("Запуск критической очистки памяти")
        
        # Запускаем callbacks
        for callback in self.critical_callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"Ошибка в critical callback: {e}")
        
        # Агрессивная очистка
        self._aggressive_cleanup()
        
        # Записываем событие
        self.oom_events.append({
            "timestamp": datetime.now(),
            "type": "critical_cleanup",
            "memory_status": self.get_memory_status()
        })
    
    def _soft_cleanup(self):
        """Мягкая очистка памяти"""
        # Сборка мусора
        collected = gc.collect()
        logger.debug(f"Мягкая очистка: собрано {collected} объектов")
        
        # Запускаем callbacks очистки
        for callback in self.cleanup_callbacks:
            try:
                callback("soft")
            except Exception as e:
                logger.error(f"Ошибка в cleanup callback: {e}")
    
    def _aggressive_cleanup(self):
        """Агрессивная очистка памяти"""
        logger.warning("Выполнение агрессивной очистки памяти")
        
        # Множественная сборка мусора
        total_collected = 0
        for _ in range(3):
            collected = gc.collect()
            total_collected += collected
        
        # Запускаем callbacks очистки
        for callback in self.cleanup_callbacks:
            try:
                callback("aggressive")
            except Exception as e:
                logger.error(f"Ошибка в cleanup callback: {e}")
        
        logger.info(f"Агрессивная очистка завершена: собрано {total_collected} объектов")
        
        # Записываем событие
        self.cleanup_events.append({
            "timestamp": datetime.now(),
            "type": "aggressive_cleanup",
            "objects_collected": total_collected,
            "memory_after": self.get_memory_status()
        })
    
    def add_warning_callback(self, callback: Callable):
        """Добавить callback для предупреждений"""
        self.warning_callbacks.append(callback)
    
    def add_critical_callback(self, callback: Callable):
        """Добавить callback для критических ситуаций"""
        self.critical_callbacks.append(callback)
    
    def add_cleanup_callback(self, callback: Callable):
        """Добавить callback для очистки"""
        self.cleanup_callbacks.append(callback)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Получить статистику OOM защиты"""
        return {
            "protection_enabled": self.protection_enabled,
            "oom_events_count": len(self.oom_events),
            "memory_warnings_count": len(self.memory_warnings),
            "cleanup_events_count": len(self.cleanup_events),
            "current_memory_status": self.get_memory_status(),
            "recent_events": {
                "oom_events": self.oom_events[-5:] if self.oom_events else [],
                "warnings": self.memory_warnings[-5:] if self.memory_warnings else [],
                "cleanups": self.cleanup_events[-5:] if self.cleanup_events else []
            }
        }
    
    def disable_protection(self):
        """Отключить защиту (только для отладки)"""
        self.protection_enabled = False
        logger.warning("OOM Protection отключена!")
    
    def enable_protection(self):
        """Включить защиту"""
        self.protection_enabled = True
        logger.info("OOM Protection включена")


@asynccontextmanager
async def memory_safe_operation(operation_name: str, estimated_memory_mb: float = 0):
    """Контекстный менеджер для безопасных операций с памятью"""
    oom_protection = get_oom_protection()
    
    # Проверяем память перед операцией
    if not oom_protection.check_memory_before_operation(operation_name, estimated_memory_mb):
        raise MemoryError(f"Недостаточно памяти для операции: {operation_name}")
    
    initial_memory = oom_protection.get_memory_status()
    
    try:
        yield oom_protection
    finally:
        # Проверяем память после операции
        final_memory = oom_protection.get_memory_status()
        memory_diff = final_memory["process"]["rss_mb"] - initial_memory["process"]["rss_mb"]
        
        if memory_diff > 50:  # Более 50MB разницы
            logger.warning(f"Операция {operation_name} использовала {memory_diff:.1f}MB памяти")
            
            # Если память критически высока, запускаем очистку
            if final_memory["system"]["percent"] >= oom_protection.limits.critical_memory_percent:
                oom_protection._trigger_critical_cleanup()


def get_oom_protection() -> OOMProtection:
    """Получить глобальный экземпляр OOM защиты"""
    if not hasattr(get_oom_protection, '_instance'):
        get_oom_protection._instance = OOMProtection()
    return get_oom_protection._instance


# Декоратор для автоматической защиты от OOM
def oom_protected(estimated_memory_mb: float = 0):
    """Декоратор для защиты функций от OOM"""
    def decorator(func):
        async def async_wrapper(*args, **kwargs):
            operation_name = f"{func.__name__}"
            async with memory_safe_operation(operation_name, estimated_memory_mb):
                return await func(*args, **kwargs)
        
        def sync_wrapper(*args, **kwargs):
            operation_name = f"{func.__name__}"
            oom_protection = get_oom_protection()
            
            if not oom_protection.check_memory_before_operation(operation_name, estimated_memory_mb):
                raise MemoryError(f"Недостаточно памяти для операции: {operation_name}")
            
            return func(*args, **kwargs)
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


# Глобальный экземпляр
oom_protection = get_oom_protection()
