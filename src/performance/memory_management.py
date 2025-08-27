"""
Система управления памятью и ресурсами
"""

import gc
import os
import psutil
import asyncio
import weakref
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime, timedelta
from loguru import logger
from dataclasses import dataclass
from contextlib import asynccontextmanager


@dataclass
class MemoryStats:
    """Статистика использования памяти"""
    total_mb: float
    available_mb: float
    used_mb: float
    percent: float
    process_mb: float
    timestamp: datetime


class MemoryMonitor:
    """Мониторинг использования памяти"""
    
    def __init__(self, warning_threshold: float = 80.0, critical_threshold: float = 90.0):
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold
        self.process = psutil.Process()
        self.stats_history: List[MemoryStats] = []
        self.max_history = 1000
        
        # Callbacks для уведомлений
        self.warning_callbacks: List[Callable] = []
        self.critical_callbacks: List[Callable] = []
    
    def get_current_stats(self) -> MemoryStats:
        """Получить текущую статистику памяти"""
        # Системная память
        system_memory = psutil.virtual_memory()
        
        # Память процесса
        process_memory = self.process.memory_info()
        
        stats = MemoryStats(
            total_mb=system_memory.total / (1024 * 1024),
            available_mb=system_memory.available / (1024 * 1024),
            used_mb=system_memory.used / (1024 * 1024),
            percent=system_memory.percent,
            process_mb=process_memory.rss / (1024 * 1024),
            timestamp=datetime.now()
        )
        
        # Сохраняем в историю
        self.stats_history.append(stats)
        if len(self.stats_history) > self.max_history:
            self.stats_history = self.stats_history[-self.max_history//2:]
        
        # Проверяем пороги
        self._check_thresholds(stats)
        
        return stats
    
    def _check_thresholds(self, stats: MemoryStats):
        """Проверить пороги использования памяти"""
        if stats.percent >= self.critical_threshold:
            logger.critical(f"Критическое использование памяти: {stats.percent:.1f}%")
            for callback in self.critical_callbacks:
                try:
                    callback(stats)
                except Exception as e:
                    logger.error(f"Ошибка в critical callback: {e}")
                    
        elif stats.percent >= self.warning_threshold:
            logger.warning(f"Высокое использование памяти: {stats.percent:.1f}%")
            for callback in self.warning_callbacks:
                try:
                    callback(stats)
                except Exception as e:
                    logger.error(f"Ошибка в warning callback: {e}")
    
    def add_warning_callback(self, callback: Callable):
        """Добавить callback для предупреждений"""
        self.warning_callbacks.append(callback)
    
    def add_critical_callback(self, callback: Callable):
        """Добавить callback для критических ситуаций"""
        self.critical_callbacks.append(callback)
    
    def get_trend_analysis(self, minutes: int = 30) -> Dict[str, Any]:
        """Анализ тенденций использования памяти"""
        cutoff_time = datetime.now() - timedelta(minutes=minutes)
        recent_stats = [s for s in self.stats_history if s.timestamp > cutoff_time]
        
        if len(recent_stats) < 2:
            return {"status": "insufficient_data"}
        
        # Вычисляем тренд
        start_percent = recent_stats[0].percent
        end_percent = recent_stats[-1].percent
        trend = end_percent - start_percent
        
        # Средние значения
        avg_percent = sum(s.percent for s in recent_stats) / len(recent_stats)
        avg_process_mb = sum(s.process_mb for s in recent_stats) / len(recent_stats)
        
        # Пики
        max_percent = max(s.percent for s in recent_stats)
        min_percent = min(s.percent for s in recent_stats)
        
        return {
            "status": "ok",
            "period_minutes": minutes,
            "samples": len(recent_stats),
            "trend_percent": round(trend, 2),
            "avg_system_percent": round(avg_percent, 2),
            "avg_process_mb": round(avg_process_mb, 2),
            "max_percent": round(max_percent, 2),
            "min_percent": round(min_percent, 2),
            "trend_direction": "increasing" if trend > 1 else "decreasing" if trend < -1 else "stable"
        }


class ResourceManager:
    """Менеджер ресурсов с автоматической очисткой"""
    
    def __init__(self):
        self.tracked_objects: Dict[str, weakref.ReferenceType] = {}
        self.cleanup_functions: Dict[str, Callable] = {}
        self.memory_monitor = MemoryMonitor()
        
        # Настраиваем автоматическую очистку при высоком использовании памяти
        self.memory_monitor.add_warning_callback(self._on_memory_warning)
        self.memory_monitor.add_critical_callback(self._on_memory_critical)
    
    def track_object(self, obj_id: str, obj: Any, cleanup_func: Optional[Callable] = None):
        """Отслеживать объект для автоматической очистки"""
        def cleanup_callback(ref):
            if obj_id in self.tracked_objects:
                del self.tracked_objects[obj_id]
            if obj_id in self.cleanup_functions:
                del self.cleanup_functions[obj_id]
        
        self.tracked_objects[obj_id] = weakref.ref(obj, cleanup_callback)
        
        if cleanup_func:
            self.cleanup_functions[obj_id] = cleanup_func
        
        logger.debug(f"Объект {obj_id} добавлен в отслеживание")
    
    def cleanup_object(self, obj_id: str) -> bool:
        """Принудительно очистить объект"""
        if obj_id in self.cleanup_functions:
            try:
                self.cleanup_functions[obj_id]()
                logger.debug(f"Объект {obj_id} очищен")
                return True
            except Exception as e:
                logger.error(f"Ошибка очистки объекта {obj_id}: {e}")
        
        return False
    
    def force_cleanup(self):
        """Принудительная очистка всех отслеживаемых объектов"""
        cleanup_count = 0
        
        for obj_id in list(self.cleanup_functions.keys()):
            if self.cleanup_object(obj_id):
                cleanup_count += 1
        
        # Принудительная сборка мусора
        collected = gc.collect()
        
        logger.info(f"Принудительная очистка: {cleanup_count} объектов, "
                   f"собрано {collected} объектов мусора")
        
        return cleanup_count
    
    def _on_memory_warning(self, stats: MemoryStats):
        """Обработка предупреждения о памяти"""
        logger.warning(f"Предупреждение о памяти: {stats.percent:.1f}%, "
                      f"процесс: {stats.process_mb:.1f}MB")
        
        # Мягкая очистка - только устаревшие объекты
        self._gentle_cleanup()
    
    def _on_memory_critical(self, stats: MemoryStats):
        """Обработка критической ситуации с памятью"""
        logger.critical(f"Критическая ситуация с памятью: {stats.percent:.1f}%, "
                       f"процесс: {stats.process_mb:.1f}MB")
        
        # Агрессивная очистка
        self.force_cleanup()
    
    def _gentle_cleanup(self):
        """Мягкая очистка ресурсов"""
        # Запускаем сборку мусора
        collected = gc.collect()
        logger.debug(f"Мягкая очистка: собрано {collected} объектов")
    
    def get_resource_stats(self) -> Dict[str, Any]:
        """Получить статистику ресурсов"""
        alive_objects = sum(1 for ref in self.tracked_objects.values() if ref() is not None)
        
        return {
            "tracked_objects": len(self.tracked_objects),
            "alive_objects": alive_objects,
            "cleanup_functions": len(self.cleanup_functions),
            "memory_stats": self.memory_monitor.get_current_stats().__dict__
        }


class LargeFileHandler:
    """Обработчик больших файлов с контролем памяти"""
    
    def __init__(self, max_memory_mb: float = 500.0):
        self.max_memory_bytes = max_memory_mb * 1024 * 1024
        self.temp_files: List[str] = []
    
    @asynccontextmanager
    async def handle_large_file(self, file_path: str):
        """Контекстный менеджер для работы с большими файлами"""
        initial_memory = psutil.Process().memory_info().rss
        
        try:
            # Проверяем размер файла
            file_size = os.path.getsize(file_path)
            
            if file_size > self.max_memory_bytes:
                # Обрабатываем по частям
                yield await self._process_in_chunks(file_path)
            else:
                # Обрабатываем целиком с мониторингом
                yield await self._process_with_monitoring(file_path)
                
        finally:
            # Очистка временных файлов
            await self._cleanup_temp_files()
            
            # Проверяем утечки памяти
            final_memory = psutil.Process().memory_info().rss
            memory_diff = (final_memory - initial_memory) / (1024 * 1024)
            
            if memory_diff > 50:  # Более 50MB разницы
                logger.warning(f"Возможная утечка памяти: +{memory_diff:.1f}MB")
                gc.collect()
    
    async def _process_in_chunks(self, file_path: str):
        """Обработка файла по частям"""
        logger.info(f"Обработка большого файла {file_path} по частям")
        
        # Здесь будет логика разбиения на части
        # Пока возвращаем путь к файлу
        return file_path
    
    async def _process_with_monitoring(self, file_path: str):
        """Обработка с мониторингом памяти"""
        logger.debug(f"Обработка файла {file_path} с мониторингом памяти")
        return file_path
    
    async def _cleanup_temp_files(self):
        """Очистка временных файлов"""
        for temp_file in self.temp_files:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                    logger.debug(f"Удален временный файл: {temp_file}")
            except Exception as e:
                logger.error(f"Ошибка удаления временного файла {temp_file}: {e}")
        
        self.temp_files.clear()


class MemoryOptimizer:
    """Оптимизатор использования памяти"""
    
    def __init__(self):
        self.resource_manager = ResourceManager()
        self.memory_monitor = MemoryMonitor()
        
        # Настройки оптимизации
        self.gc_threshold = 85.0  # Процент использования памяти для запуска GC
        self.optimization_interval = 300  # 5 минут
        
        self.optimization_task: Optional[asyncio.Task] = None
        self.is_optimizing = False
    
    def start_optimization(self):
        """Запустить автоматическую оптимизацию"""
        if not self.is_optimizing:
            self.is_optimizing = True
            self.optimization_task = asyncio.create_task(self._optimization_loop())
            logger.info("Автоматическая оптимизация памяти запущена")
    
    def stop_optimization(self):
        """Остановить автоматическую оптимизацию"""
        if self.optimization_task:
            self.optimization_task.cancel()
            self.is_optimizing = False
            logger.info("Автоматическая оптимизация памяти остановлена")
    
    async def _optimization_loop(self):
        """Цикл автоматической оптимизации"""
        try:
            while self.is_optimizing:
                stats = self.memory_monitor.get_current_stats()
                
                if stats.percent > self.gc_threshold:
                    await self.optimize_memory()
                
                await asyncio.sleep(self.optimization_interval)
                
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Ошибка в цикле оптимизации памяти: {e}")
    
    async def optimize_memory(self) -> Dict[str, Any]:
        """Оптимизировать использование памяти"""
        start_stats = self.memory_monitor.get_current_stats()
        logger.info(f"Начало оптимизации памяти: {start_stats.percent:.1f}%")
        
        # 1. Очистка отслеживаемых ресурсов
        cleanup_count = self.resource_manager.force_cleanup()
        
        # 2. Принудительная сборка мусора
        collected = gc.collect()
        
        # 3. Ждем немного для стабилизации
        await asyncio.sleep(1)
        
        end_stats = self.memory_monitor.get_current_stats()
        memory_freed = start_stats.process_mb - end_stats.process_mb
        
        result = {
            "memory_before_mb": round(start_stats.process_mb, 2),
            "memory_after_mb": round(end_stats.process_mb, 2),
            "memory_freed_mb": round(memory_freed, 2),
            "objects_cleaned": cleanup_count,
            "gc_collected": collected,
            "system_percent_before": round(start_stats.percent, 2),
            "system_percent_after": round(end_stats.percent, 2)
        }
        
        logger.info(f"Оптимизация завершена: освобождено {memory_freed:.1f}MB, "
                   f"очищено {cleanup_count} объектов, собрано {collected} объектов GC")
        
        return result
    
    def get_optimization_stats(self) -> Dict[str, Any]:
        """Получить статистику оптимизации"""
        memory_stats = self.memory_monitor.get_current_stats()
        resource_stats = self.resource_manager.get_resource_stats()
        trend_analysis = self.memory_monitor.get_trend_analysis()
        
        return {
            "is_optimizing": self.is_optimizing,
            "current_memory": memory_stats.__dict__,
            "resources": resource_stats,
            "trend": trend_analysis,
            "thresholds": {
                "warning": self.memory_monitor.warning_threshold,
                "critical": self.memory_monitor.critical_threshold,
                "gc_trigger": self.gc_threshold
            }
        }


# Глобальные экземпляры
memory_optimizer = MemoryOptimizer()
resource_manager = ResourceManager()


# Декоратор для автоматического управления памятью
def memory_managed(cleanup_func: Optional[Callable] = None):
    """Декоратор для автоматического управления памятью объектов"""
    def decorator(cls):
        original_init = cls.__init__
        
        def new_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            
            # Регистрируем объект для отслеживания
            obj_id = f"{cls.__name__}_{id(self)}"
            resource_manager.track_object(obj_id, self, cleanup_func)
        
        cls.__init__ = new_init
        return cls
    
    return decorator
