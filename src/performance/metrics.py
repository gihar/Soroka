"""
Система мониторинга производительности и сбора метрик
"""

import time
import asyncio
import psutil
import threading
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import defaultdict, deque
from loguru import logger
import json
import sys
import os

# Добавляем корневую директорию в путь для импорта database
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from database import db


@dataclass
class PerformanceMetric:
    """Метрика производительности"""
    name: str
    value: float
    unit: str
    timestamp: datetime
    tags: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "timestamp": self.timestamp.isoformat(),
            "tags": self.tags
        }


@dataclass
class ProcessingMetrics:
    """Метрики обработки файла"""
    file_name: str
    user_id: int
    start_time: datetime
    end_time: Optional[datetime] = None
    
    # Этапы обработки
    download_duration: float = 0.0
    validation_duration: float = 0.0
    conversion_duration: float = 0.0
    transcription_duration: float = 0.0
    diarization_duration: float = 0.0
    llm_duration: float = 0.0
    formatting_duration: float = 0.0
    
    # Характеристики файла
    file_size_bytes: int = 0
    file_format: str = ""
    audio_duration_seconds: float = 0.0
    
    # Результаты
    transcription_length: int = 0
    speakers_count: int = 0
    protocol_quality_score: float = 0.0  # Оценка качества протокола (0-1)
    
    # Метрики структурированного представления
    structure_building_duration: float = 0.0
    topics_extracted: int = 0
    decisions_extracted: int = 0
    actions_extracted: int = 0
    structure_validation_passed: bool = False
    
    # Метрики кеширования токенов
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_cached_tokens: int = 0
    cache_hit_rate: float = 0.0  # 0.0 - 1.0
    estimated_cost_without_cache: float = 0.0
    estimated_cost_with_cache: float = 0.0
    estimated_cost_saved: float = 0.0
    
    error_occurred: bool = False
    error_stage: str = ""
    error_message: str = ""
    
    @property
    def total_duration(self) -> float:
        """Общее время обработки"""
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0
    
    @property
    def efficiency_score(self) -> float:
        """Коэффициент эффективности (время_аудио / время_обработки)"""
        if self.total_duration > 0 and self.audio_duration_seconds > 0:
            return self.audio_duration_seconds / self.total_duration
        return 0.0
    
    def add_cache_metrics(self, cached_tokens: int, prompt_tokens: int, 
                         cost_saved: float = 0.0, cost_with: float = 0.0, 
                         cost_without: float = 0.0):
        """
        Добавить метрики кеширования из одного LLM вызова
        
        Args:
            cached_tokens: Количество кешированных токенов
            prompt_tokens: Общее количество prompt токенов
            cost_saved: Сэкономленная стоимость
            cost_with: Стоимость с кешированием
            cost_without: Стоимость без кеширования
        """
        self.total_cached_tokens += cached_tokens
        self.total_prompt_tokens += prompt_tokens
        self.estimated_cost_saved += cost_saved
        self.estimated_cost_with_cache += cost_with
        self.estimated_cost_without_cache += cost_without
        
        # Пересчитываем общий cache hit rate
        if self.total_prompt_tokens > 0:
            self.cache_hit_rate = self.total_cached_tokens / self.total_prompt_tokens
    
    def get_cache_summary(self) -> Dict[str, Any]:
        """
        Получить сводку по кешированию токенов
        
        Returns:
            Словарь с метриками кеширования
        """
        savings_percent = 0.0
        if self.estimated_cost_without_cache > 0:
            savings_percent = (self.estimated_cost_saved / self.estimated_cost_without_cache) * 100
        
        return {
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_cached_tokens": self.total_cached_tokens,
            "cache_hit_rate": round(self.cache_hit_rate, 3),
            "cache_hit_rate_percent": round(self.cache_hit_rate * 100, 1),
            "cost_with_cache": round(self.estimated_cost_with_cache, 4),
            "cost_without_cache": round(self.estimated_cost_without_cache, 4),
            "cost_saved": round(self.estimated_cost_saved, 4),
            "savings_percent": round(savings_percent, 1)
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Безопасное преобразование в словарь (исключает несериализуемые объекты)"""
        result = {}
        
        # Безопасно добавляем только сериализуемые поля
        safe_fields = {
            "file_name": self.file_name,
            "user_id": self.user_id,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "total_duration": self.total_duration,
            "download_duration": self.download_duration,
            "validation_duration": self.validation_duration,
            "conversion_duration": self.conversion_duration,
            "transcription_duration": self.transcription_duration,
            "diarization_duration": self.diarization_duration,
            "llm_duration": self.llm_duration,
            "formatting_duration": self.formatting_duration,
            "file_size_bytes": self.file_size_bytes,
            "file_format": self.file_format,
            "audio_duration_seconds": self.audio_duration_seconds,
            "transcription_length": self.transcription_length,
            "speakers_count": self.speakers_count,
            "efficiency_score": self.efficiency_score,
            "error_occurred": self.error_occurred,
            "error_stage": self.error_stage,
            "error_message": self.error_message
        }
        
        # Добавляем только JSON-сериализуемые значения
        for key, value in safe_fields.items():
            try:
                # Проверяем, что значение JSON-сериализуемо
                import json
                json.dumps(value)
                result[key] = value
            except (TypeError, ValueError):
                # Если не сериализуемо, пропускаем или заменяем на строку
                if value is not None:
                    result[key] = str(value) if not isinstance(value, (list, dict)) else "non_serializable"
                else:
                    result[key] = None
        
        return result


class MetricsCollector:
    """Сборщик метрик производительности"""
    
    def __init__(self, retention_hours: int = 24):
        self.retention_period = timedelta(hours=retention_hours)
        
        # Хранилище метрик
        self.metrics: List[PerformanceMetric] = []
        self.processing_metrics: List[ProcessingMetrics] = []
        
        # Системные метрики
        self.system_metrics = deque(maxlen=1000)  # Последние 1000 замеров
        
        # Агрегированные данные
        self.hourly_stats = defaultdict(lambda: {
            "requests": 0,
            "total_duration": 0.0,
            "errors": 0,
            "avg_duration": 0.0
        })
        
        # Фоновая задача для сбора системных метрик
        self.monitoring_task: Optional[asyncio.Task] = None
        self.is_monitoring = False
        self._initialized = False
    
    async def initialize(self):
        """Загрузить данные из БД при инициализации"""
        if self._initialized:
            return
        
        try:
            # Загружаем метрики обработки за последние 24 часа
            metrics_data = await db.get_processing_metrics(hours=24)
            for metric_dict in metrics_data:
                metric = ProcessingMetrics(
                    file_name=metric_dict['file_name'],
                    user_id=metric_dict['user_id'],
                    start_time=datetime.fromisoformat(metric_dict['start_time']),
                    end_time=datetime.fromisoformat(metric_dict['end_time']) if metric_dict['end_time'] else None,
                    download_duration=metric_dict.get('download_duration', 0.0),
                    validation_duration=metric_dict.get('validation_duration', 0.0),
                    conversion_duration=metric_dict.get('conversion_duration', 0.0),
                    transcription_duration=metric_dict.get('transcription_duration', 0.0),
                    diarization_duration=metric_dict.get('diarization_duration', 0.0),
                    llm_duration=metric_dict.get('llm_duration', 0.0),
                    formatting_duration=metric_dict.get('formatting_duration', 0.0),
                    file_size_bytes=metric_dict.get('file_size_bytes', 0),
                    file_format=metric_dict.get('file_format', ''),
                    audio_duration_seconds=metric_dict.get('audio_duration_seconds', 0.0),
                    transcription_length=metric_dict.get('transcription_length', 0),
                    speakers_count=metric_dict.get('speakers_count', 0),
                    error_occurred=bool(metric_dict.get('error_occurred', False)),
                    error_stage=metric_dict.get('error_stage', ''),
                    error_message=metric_dict.get('error_message', '')
                )
                self.processing_metrics.append(metric)
                
                # Восстанавливаем почасовую статистику
                hour_key = metric.start_time.strftime("%Y-%m-%d-%H")
                self.hourly_stats[hour_key]["requests"] += 1
                if metric.end_time:
                    self.hourly_stats[hour_key]["total_duration"] += metric.total_duration
                if metric.error_occurred:
                    self.hourly_stats[hour_key]["errors"] += 1
                if self.hourly_stats[hour_key]["requests"] > 0:
                    self.hourly_stats[hour_key]["avg_duration"] = (
                        self.hourly_stats[hour_key]["total_duration"] / 
                        self.hourly_stats[hour_key]["requests"]
                    )
            
            logger.info(f"Загружено {len(self.processing_metrics)} метрик обработки из БД")
            self._initialized = True
        except Exception as e:
            logger.error(f"Ошибка загрузки метрик из БД: {e}")
    
    def start_monitoring(self):
        """Запустить мониторинг системных метрик"""
        if not self.is_monitoring:
            self.is_monitoring = True
            self.monitoring_task = asyncio.create_task(self._collect_system_metrics())
            logger.info("Мониторинг производительности запущен")
    
    def stop_monitoring(self):
        """Остановить мониторинг"""
        if self.monitoring_task:
            self.monitoring_task.cancel()
            self.is_monitoring = False
            logger.info("Мониторинг производительности остановлен")
    
    async def _collect_system_metrics(self):
        """Сбор системных метрик в фоне"""
        try:
            while self.is_monitoring:
                timestamp = datetime.now()
                
                # CPU метрики
                cpu_percent = psutil.cpu_percent(interval=1)
                self.add_metric("system.cpu.usage", cpu_percent, "percent", timestamp)
                
                # Память
                memory = psutil.virtual_memory()
                self.add_metric("system.memory.usage", memory.percent, "percent", timestamp)
                self.add_metric("system.memory.available", memory.available / (1024**3), "GB", timestamp)
                
                # Диск
                disk = psutil.disk_usage('/')
                self.add_metric("system.disk.usage", disk.percent, "percent", timestamp)
                self.add_metric("system.disk.free", disk.free / (1024**3), "GB", timestamp)
                
                # Сеть (если доступно)
                try:
                    net_io = psutil.net_io_counters()
                    self.add_metric("system.network.bytes_sent", net_io.bytes_sent, "bytes", timestamp)
                    self.add_metric("system.network.bytes_recv", net_io.bytes_recv, "bytes", timestamp)
                except:
                    pass
                
                # Сохраняем для быстрого доступа
                self.system_metrics.append({
                    "timestamp": timestamp,
                    "cpu": cpu_percent,
                    "memory": memory.percent,
                    "disk": disk.percent
                })
                
                await asyncio.sleep(30)  # Собираем каждые 30 секунд
                
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Ошибка в мониторинге системных метрик: {e}")
    
    def add_metric(self, name: str, value: float, unit: str, 
                   timestamp: Optional[datetime] = None, tags: Optional[Dict[str, str]] = None):
        """Добавить метрику"""
        if timestamp is None:
            timestamp = datetime.now()
        
        metric = PerformanceMetric(
            name=name,
            value=value,
            unit=unit,
            timestamp=timestamp,
            tags=tags or {}
        )
        
        self.metrics.append(metric)
        
        # Очищаем старые метрики
        cutoff_time = datetime.now() - self.retention_period
        self.metrics = [m for m in self.metrics if m.timestamp > cutoff_time]
    
    def start_processing_metrics(self, file_name: str, user_id: int) -> ProcessingMetrics:
        """Начать сбор метрик обработки файла"""
        metrics = ProcessingMetrics(
            file_name=file_name,
            user_id=user_id,
            start_time=datetime.now()
        )
        
        self.processing_metrics.append(metrics)
        return metrics
    
    def finish_processing_metrics(self, metrics: ProcessingMetrics, 
                                 error: Optional[Exception] = None):
        """Завершить сбор метрик обработки"""
        metrics.end_time = datetime.now()
        
        if error:
            metrics.error_occurred = True
            metrics.error_message = str(error)
        
        # Добавляем в почасовую статистику
        hour_key = metrics.start_time.strftime("%Y-%m-%d-%H")
        self.hourly_stats[hour_key]["requests"] += 1
        self.hourly_stats[hour_key]["total_duration"] += metrics.total_duration
        
        if metrics.error_occurred:
            self.hourly_stats[hour_key]["errors"] += 1
        
        # Пересчитываем среднее время
        if self.hourly_stats[hour_key]["requests"] > 0:
            self.hourly_stats[hour_key]["avg_duration"] = (
                self.hourly_stats[hour_key]["total_duration"] / 
                self.hourly_stats[hour_key]["requests"]
            )
        
        # Добавляем метрики
        self.add_metric("processing.duration", metrics.total_duration, "seconds", 
                       metrics.end_time, {"user_id": str(metrics.user_id), "file_format": metrics.file_format})
        
        if metrics.efficiency_score > 0:
            self.add_metric("processing.efficiency", metrics.efficiency_score, "ratio",
                           metrics.end_time, {"file_format": metrics.file_format})
        
        # Сохраняем в БД
        try:
            loop = asyncio.get_event_loop()
            loop.create_task(self._save_processing_metrics_to_db(metrics))
        except Exception as e:
            logger.error(f"Ошибка сохранения метрик в БД: {e}")
    
    async def _save_processing_metrics_to_db(self, metrics: ProcessingMetrics):
        """Сохранить метрики обработки в БД"""
        try:
            metric_data = {
                'file_name': metrics.file_name,
                'user_id': metrics.user_id,
                'start_time': metrics.start_time.isoformat(),
                'end_time': metrics.end_time.isoformat() if metrics.end_time else None,
                'download_duration': metrics.download_duration,
                'validation_duration': metrics.validation_duration,
                'conversion_duration': metrics.conversion_duration,
                'transcription_duration': metrics.transcription_duration,
                'diarization_duration': metrics.diarization_duration,
                'llm_duration': metrics.llm_duration,
                'formatting_duration': metrics.formatting_duration,
                'file_size_bytes': metrics.file_size_bytes,
                'file_format': metrics.file_format,
                'audio_duration_seconds': metrics.audio_duration_seconds,
                'transcription_length': metrics.transcription_length,
                'speakers_count': metrics.speakers_count,
                'error_occurred': metrics.error_occurred,
                'error_stage': metrics.error_stage,
                'error_message': metrics.error_message
            }
            await db.save_processing_metric(metric_data)
        except Exception as e:
            logger.error(f"Ошибка сохранения метрик обработки: {e}")
    
    def get_current_stats(self) -> Dict[str, Any]:
        """Получить текущую статистику"""
        now = datetime.now()
        last_hour = now - timedelta(hours=1)
        last_24h = now - timedelta(hours=24)
        
        # Метрики за последний час
        recent_processing = [m for m in self.processing_metrics if m.start_time > last_hour]
        daily_processing = [m for m in self.processing_metrics if m.start_time > last_24h]
        
        # Системные метрики (последние)
        latest_system = None
        if self.system_metrics:
            latest_system = self.system_metrics[-1]
        
        # Статистика обработки
        total_requests = len(daily_processing)
        successful_requests = len([m for m in daily_processing if not m.error_occurred])
        error_rate = ((total_requests - successful_requests) / total_requests * 100) if total_requests > 0 else 0
        
        avg_duration = 0
        if successful_requests > 0:
            successful_metrics = [m for m in daily_processing if not m.error_occurred and m.end_time]
            if successful_metrics:
                avg_duration = sum(m.total_duration for m in successful_metrics) / len(successful_metrics)
        
        # Efficiency статистика
        efficiency_scores = [m.efficiency_score for m in daily_processing 
                           if not m.error_occurred and m.efficiency_score > 0]
        avg_efficiency = sum(efficiency_scores) / len(efficiency_scores) if efficiency_scores else 0
        
        return {
            "timestamp": now.isoformat(),
            "system": {
                "cpu_percent": latest_system["cpu"] if latest_system else 0,
                "memory_percent": latest_system["memory"] if latest_system else 0,
                "disk_percent": latest_system["disk"] if latest_system else 0,
            },
            "processing": {
                "requests_24h": total_requests,
                "requests_1h": len(recent_processing),
                "success_rate_percent": round(100 - error_rate, 2),
                "error_rate_percent": round(error_rate, 2),
                "avg_duration_seconds": round(avg_duration, 2),
                "avg_efficiency_ratio": round(avg_efficiency, 3)
            },
            "performance": {
                "cache_hit_rate": 0,  # Будет заполнено из cache_system
                "active_connections": 0,  # Будет заполнено из connection pool
                "queue_size": 0  # Будет заполнено из task queue
            }
        }
    
    def get_detailed_report(self) -> Dict[str, Any]:
        """Получить детальный отчет по производительности"""
        now = datetime.now()
        last_24h = now - timedelta(hours=24)
        
        # Обработка за 24 часа
        recent_processing = [m for m in self.processing_metrics 
                           if m.start_time > last_24h and m.end_time]
        
        if not recent_processing:
            return {"message": "Нет данных за последние 24 часа"}
        
        # Группируем по этапам
        stage_durations = {
            "download": [m.download_duration for m in recent_processing if m.download_duration > 0],
            "validation": [m.validation_duration for m in recent_processing if m.validation_duration > 0],
            "conversion": [m.conversion_duration for m in recent_processing if m.conversion_duration > 0],
            "transcription": [m.transcription_duration for m in recent_processing if m.transcription_duration > 0],
            "diarization": [m.diarization_duration for m in recent_processing if m.diarization_duration > 0],
            "llm": [m.llm_duration for m in recent_processing if m.llm_duration > 0],
            "formatting": [m.formatting_duration for m in recent_processing if m.formatting_duration > 0]
        }
        
        # Статистика по этапам
        stage_stats = {}
        for stage, durations in stage_durations.items():
            if durations:
                stage_stats[stage] = {
                    "count": len(durations),
                    "avg_duration": round(sum(durations) / len(durations), 2),
                    "min_duration": round(min(durations), 2),
                    "max_duration": round(max(durations), 2),
                    "total_duration": round(sum(durations), 2)
                }
        
        # Топ медленных запросов
        slowest_requests = sorted(recent_processing, 
                                key=lambda x: x.total_duration, reverse=True)[:10]
        
        # Ошибки
        errors = [m for m in recent_processing if m.error_occurred]
        error_breakdown = defaultdict(int)
        for error in errors:
            error_breakdown[error.error_stage] += 1
        
        return {
            "period": "24 hours",
            "total_requests": len(recent_processing),
            "successful_requests": len(recent_processing) - len(errors),
            "error_count": len(errors),
            "stage_performance": stage_stats,
            "slowest_requests": [
                {
                    "file_name": m.file_name,
                    "duration": round(m.total_duration, 2),
                    "efficiency": round(m.efficiency_score, 3),
                    "file_size_mb": round(m.file_size_bytes / (1024*1024), 2)
                } for m in slowest_requests
            ],
            "errors_by_stage": dict(error_breakdown)
        }
    
    def export_metrics(self, format: str = "json") -> str:
        """Экспортировать метрики"""
        if format == "json":
            try:
                # Безопасно собираем метрики
                safe_metrics = []
                for m in self.metrics[-1000:]:
                    try:
                        safe_metrics.append(m.to_dict())
                    except Exception as e:
                        logger.warning(f"Пропускаем метрику из-за ошибки сериализации: {e}")
                
                safe_processing = []
                for m in self.processing_metrics[-100:]:
                    try:
                        safe_processing.append(m.to_dict())
                    except Exception as e:
                        logger.warning(f"Пропускаем processing метрику из-за ошибки сериализации: {e}")
                
                data = {
                    "exported_at": datetime.now().isoformat(),
                    "metrics_count": len(self.metrics),
                    "processing_records": len(self.processing_metrics),
                    "metrics": safe_metrics,
                    "processing": safe_processing
                }
                return json.dumps(data, indent=2, ensure_ascii=False)
                
            except Exception as e:
                logger.error(f"Ошибка экспорта метрик: {e}")
                # Возвращаем минимальную информацию в случае ошибки
                return json.dumps({
                    "exported_at": datetime.now().isoformat(),
                    "error": f"Ошибка экспорта: {str(e)}",
                    "metrics_count": len(self.metrics),
                    "processing_records": len(self.processing_metrics)
                }, indent=2, ensure_ascii=False)
        
        raise ValueError(f"Неподдерживаемый формат: {format}")


# Глобальный сборщик метрик
metrics_collector = MetricsCollector()


class PerformanceTimer:
    """Контекстный менеджер для измерения времени выполнения"""
    
    def __init__(self, name: str, metrics_collector: MetricsCollector, 
                 tags: Optional[Dict[str, str]] = None):
        self.name = name
        self.metrics_collector = metrics_collector
        self.tags = tags or {}
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time:
            duration = time.time() - self.start_time
            self.metrics_collector.add_metric(
                f"timer.{self.name}",
                duration,
                "seconds",
                tags=self.tags
            )


def performance_timer(name: str, tags: Optional[Dict[str, str]] = None):
    """Декоратор для измерения времени выполнения функций"""
    def decorator(func):
        async def async_wrapper(*args, **kwargs):
            with PerformanceTimer(f"function.{func.__name__}", metrics_collector, tags):
                return await func(*args, **kwargs)
        
        def sync_wrapper(*args, **kwargs):
            with PerformanceTimer(f"function.{func.__name__}", metrics_collector, tags):
                return func(*args, **kwargs)
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    
    return decorator
