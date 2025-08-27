"""
Оптимизированный сервис обработки с улучшенной производительностью
"""

import asyncio
import time
import os
import aiofiles
from typing import Dict, Any, Optional
from loguru import logger

from services.base_processing_service import BaseProcessingService
from models.processing import ProcessingRequest, ProcessingResult
from exceptions.processing import ProcessingError
from performance.cache_system import performance_cache, cache_transcription, cache_llm_response
from performance.metrics import metrics_collector, PerformanceTimer, performance_timer
from performance.async_optimization import (
    task_pool, thread_manager, optimized_file_processing,
    OptimizedHTTPClient, async_lru_cache
)
from performance.memory_management import memory_optimizer


class OptimizedProcessingService(BaseProcessingService):
    """Сервис обработки с оптимизацией производительности"""
    
    def __init__(self):
        super().__init__()
        
        # Мониторинг будет запущен при первом использовании
        self._monitoring_started = False
    
    @performance_timer("file_processing")
    async def process_file(self, request: ProcessingRequest, progress_tracker=None) -> ProcessingResult:
        """Оптимизированная обработка файла"""
        # Запускаем мониторинг при первом использовании
        await self._ensure_monitoring_started()
        
        # Создаем метрики для отслеживания
        processing_metrics = metrics_collector.start_processing_metrics(
            request.file_name, request.user_id
        )
        
        try:
            # Начинаем отслеживание прогресса
            if progress_tracker:
                await progress_tracker.start_stage("validation")
            
            # Проверяем кэш полного результата
            cache_key = self._generate_result_cache_key(request)
            cached_result = await performance_cache.get(cache_key)
            
            if cached_result:
                logger.info(f"Найден кэшированный результат для {request.file_name}")
                processing_metrics.end_time = processing_metrics.start_time  # Мгновенный результат
                metrics_collector.finish_processing_metrics(processing_metrics)
                if progress_tracker:
                    await progress_tracker.complete_all()
                return cached_result
            
            # Если кэша нет, выполняем оптимизированную обработку
            result = await self._process_file_optimized(request, processing_metrics, progress_tracker)
            
            # Кэшируем результат
            await performance_cache.set(
                cache_key, result, 
                cache_type="processing_result"
            )
            
            metrics_collector.finish_processing_metrics(processing_metrics)
            return result
            
        except Exception as e:
            logger.error(f"Ошибка в оптимизированной обработке {request.file_name}: {e}")
            metrics_collector.finish_processing_metrics(processing_metrics, e)
            raise
    
    async def _process_file_optimized(self, request: ProcessingRequest, 
                                    processing_metrics, progress_tracker=None) -> ProcessingResult:
        """Внутренняя оптимизированная обработка"""
        
        async with optimized_file_processing() as resources:
            http_client = resources["http_client"]
            
            # Этап 1: Параллельная загрузка данных пользователя и шаблона
            with PerformanceTimer("data_loading", metrics_collector):
                user_task = asyncio.create_task(
                    self.user_service.get_user_by_telegram_id(request.user_id)
                )
                template_task = asyncio.create_task(
                    self.template_service.get_template_by_id(request.template_id)
                )
                
                user, template = await asyncio.gather(user_task, template_task)
                
                if not user:
                    raise ProcessingError(f"Пользователь {request.user_id} не найден", 
                                        request.file_name, "validation")
            
            processing_metrics.validation_duration = 0.5  # Примерное время
            
            # Этап 2: Получение файла
            if progress_tracker:
                if request.is_external_file:
                    await progress_tracker.start_stage("file_preparation")
                else:
                    await progress_tracker.start_stage("download")
            
            with PerformanceTimer("file_download", metrics_collector):
                if request.is_external_file:
                    # Для внешних файлов путь уже указан
                    temp_file_path = request.file_path
                    
                    # Получаем размер файла
                    if os.path.exists(temp_file_path):
                        file_size = os.path.getsize(temp_file_path)
                        processing_metrics.file_size_bytes = file_size
                        processing_metrics.download_duration = 0.1  # Минимальное время
                    else:
                        raise ProcessingError(f"Файл не найден: {temp_file_path}", 
                                            request.file_name, "file_preparation")
                else:
                    # Для Telegram файлов - скачиваем как обычно
                    file_url = await self.file_service.get_telegram_file_url(request.file_id)
                    temp_file_path = f"temp/{request.file_name}"
                    
                    download_result = await http_client.download_file(file_url, temp_file_path)
                    
                    if not download_result["success"]:
                        raise ProcessingError(f"Ошибка скачивания: {download_result['error']}", 
                                            request.file_name, "download")
                    
                    processing_metrics.download_duration = download_result["duration"]
                    processing_metrics.file_size_bytes = download_result["bytes_downloaded"]
                
                processing_metrics.file_format = os.path.splitext(request.file_name)[1]
            
            # Этап 3: Кэшированная транскрипция
            if progress_tracker:
                await progress_tracker.start_stage("transcription")
                
            transcription_result = await self._optimized_transcription(
                temp_file_path, request, processing_metrics, progress_tracker
            )
            
            # Этап 4: Кэшированная генерация LLM
            if progress_tracker:
                await progress_tracker.start_stage("llm_processing")
                
            llm_result = await self._optimized_llm_generation(
                transcription_result, template, request, processing_metrics
            )
            
            # Этап 5: Быстрое форматирование
            if progress_tracker:
                await progress_tracker.start_stage("formatting")
                
            with PerformanceTimer("formatting", metrics_collector):
                processing_metrics.formatting_duration = 0.1
                
                protocol_text = self._format_protocol(
                    template, llm_result, transcription_result
                )
            
            # Очистка временного файла в фоне (только для внешних файлов)
            if request.is_external_file:
                asyncio.create_task(self._cleanup_temp_file(temp_file_path))
            
            # Создаем результат
            return ProcessingResult(
                transcription_result=transcription_result,
                protocol_text=protocol_text,
                template_used=template.model_dump() if hasattr(template, 'model_dump') else template.__dict__,
                llm_provider_used=request.llm_provider,
                processing_duration=processing_metrics.total_duration
            )
    
    @cache_transcription()
    async def _optimized_transcription(self, file_path: str, request: ProcessingRequest,
                                     processing_metrics, progress_tracker=None) -> Any:
        """Оптимизированная транскрипция с кэшированием"""
        
        # Создаем ключ кэша на основе содержимого файла
        file_hash = await self._calculate_file_hash(file_path)
        cache_key = f"transcription:{file_hash}:{request.language}"
        
        # Проверяем кэш
        cached_transcription = await performance_cache.get(cache_key)
        if cached_transcription:
            logger.info(f"Использован кэшированный результат транскрипции")
            processing_metrics.transcription_duration = 0.1  # Мгновенно из кэша
            return cached_transcription
        
        # Выполняем транскрипцию в отдельном потоке для не блокирования
        with PerformanceTimer("transcription", metrics_collector):
            start_time = time.time()
            
            # Создаем thread-safe колбэк для обновления прогресса
            def progress_callback(percent, message):
                """Thread-safe колбэк для обновления прогресса транскрипции"""
                if progress_tracker:
                    try:
                        # Получаем текущий event loop
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            # Планируем выполнение в основном потоке
                            asyncio.run_coroutine_threadsafe(
                                progress_tracker.update_stage_progress(
                                    "transcription", percent, message
                                ), loop
                            )
                    except RuntimeError:
                        # Если нет активного event loop, просто логируем
                        logger.debug(f"Progress update: {percent}% - {message}")
                    except Exception as e:
                        logger.warning(f"Ошибка при обновлении прогресса: {e}")
            
            # Используем thread pool для CPU-интенсивной задачи
            transcription_result = await thread_manager.run_in_thread(
                self._run_transcription_sync, file_path, request.language, progress_callback
            )
            
            processing_metrics.transcription_duration = time.time() - start_time
            
            # Извлекаем метрики
            if hasattr(transcription_result, 'transcription'):
                processing_metrics.transcription_length = len(transcription_result.transcription)
            
            # Если есть диаризация, показываем соответствующий этап
            if hasattr(transcription_result, 'diarization') and transcription_result.diarization:
                if progress_tracker and "diarization" in progress_tracker.stages:
                    await progress_tracker.start_stage("diarization")
                    
                diarization_data = transcription_result.diarization
                if isinstance(diarization_data, dict):
                    processing_metrics.speakers_count = diarization_data.get('total_speakers', 0)
                    processing_metrics.diarization_duration = 5.0  # Примерное время
        
        # Кэшируем результат
        await performance_cache.set(cache_key, transcription_result, cache_type="transcription")
        
        return transcription_result
    
    def _run_transcription_sync(self, file_path: str, language: str, progress_callback=None):
        """Синхронная транскрипция для выполнения в thread pool"""
        return self.transcription_service.transcribe_with_diarization(
            file_path, language, progress_callback
        )
    
    @cache_llm_response()
    async def _optimized_llm_generation(self, transcription_result: Any, template: Dict,
                                      request: ProcessingRequest, processing_metrics) -> Any:
        """Оптимизированная генерация LLM с кэшированием"""
        
        # Создаем ключ кэша на основе транскрипции и шаблона
        transcription_hash = hash(str(transcription_result.transcription))
        template_hash = hash(str(template))
        cache_key = f"llm:{request.llm_provider}:{transcription_hash}:{template_hash}"
        
        # Проверяем кэш
        cached_llm_result = await performance_cache.get(cache_key)
        if cached_llm_result:
            logger.info(f"Использован кэшированный результат LLM")
            processing_metrics.llm_duration = 0.1
            return cached_llm_result
        
        # Выполняем генерацию LLM
        with PerformanceTimer("llm_generation", metrics_collector):
            start_time = time.time()
            
            # Подготавливаем данные для LLM - извлекаем переменные из шаблона
            template_variables = self._get_template_variables_from_template(template)
            
            # Создаем задачу для LLM
            llm_task_id = f"llm_{request.user_id}_{int(time.time())}"
            
            llm_result = await task_pool.submit_task(
                llm_task_id,
                self._generate_llm_response,
                transcription_result,
                template,
                template_variables,
                request.llm_provider
            )
            
            if not llm_result.success:
                raise ProcessingError(f"Ошибка LLM: {llm_result.error}", 
                                    request.file_name, "llm")
            
            processing_metrics.llm_duration = time.time() - start_time
            
        # Кэшируем результат
        await performance_cache.set(cache_key, llm_result.result, cache_type="llm_response")
        
        return llm_result.result
    
    def _get_template_variables_from_template(self, template) -> Dict[str, str]:
        """Извлечь переменные из конкретного шаблона"""
        try:
            # Получаем содержимое шаблона правильно
            if hasattr(template, 'content'):
                template_content = template.content
            elif isinstance(template, dict):
                template_content = template.get('content', '')
            else:
                template_content = str(template)
            
            # Извлекаем переменные из шаблона
            variables_list = self.template_service.extract_template_variables(template_content)
            
            # Создаем словарь переменных (названия переменных как ключи и значения)
            template_variables = {}
            for var in variables_list:
                template_variables[var] = var  # LLM провайдер ожидает название переменной
            
            logger.info(f"Извлечены переменные из шаблона: {list(template_variables.keys())}")
            return template_variables
            
        except Exception as e:
            logger.error(f"Ошибка при извлечении переменных из шаблона: {e}")
            # Возвращаем базовый набор переменных как fallback
            return self._get_template_variables()

    async def _generate_llm_response(self, transcription_result, template, 
                                   template_variables, llm_provider):
        """Генерация ответа LLM с постобработкой"""
        llm_result = await self.llm_service.generate_protocol_with_fallback(
            llm_provider, transcription_result.transcription, template_variables,
            transcription_result.diarization if hasattr(transcription_result, 'diarization') else None
        )
        
        # Постобработка результатов - проверяем и исправляем неправильные JSON-структуры
        return self._post_process_llm_result(llm_result)
    
    def _post_process_llm_result(self, llm_result: Dict[str, Any]) -> Dict[str, Any]:
        """Постобработка результатов LLM для исправления JSON-структур в значениях"""
        if not isinstance(llm_result, dict):
            return llm_result
            
        processed_result = {}
        
        for key, value in llm_result.items():
            if isinstance(value, str):
                # Проверяем, не является ли значение JSON-строкой
                processed_value = self._fix_json_in_text(value)
                processed_result[key] = processed_value
            else:
                processed_result[key] = value
        
        return processed_result
    
    def _fix_json_in_text(self, text: str) -> str:
        """Исправляет JSON-структуры в тексте, преобразуя их в читаемый формат"""
        import json
        import re
        
        # Паттерн для поиска JSON-объектов в тексте
        json_pattern = r'\{[^{}]*\}'
        
        def replace_json_object(match):
            json_str = match.group(0)
            try:
                json_obj = json.loads(json_str)
                
                # Преобразуем JSON-объект в читаемый текст
                if isinstance(json_obj, dict):
                    if 'decision' in json_obj:
                        # Это объект решения
                        decision = json_obj.get('decision', '')
                        decision_maker = json_obj.get('decision_maker', 'Не указано')
                        return f"• {decision} (решение принял: {decision_maker})"
                    elif 'item' in json_obj:
                        # Это объект действия
                        item = json_obj.get('item', '')
                        assignee = json_obj.get('assignee', 'Не указано')
                        due = json_obj.get('due', 'Не указано')
                        status = json_obj.get('status', 'Не указано')
                        return f"• {item} - {assignee}, до {due}"
                    else:
                        # Общий случай - просто извлекаем значения
                        values = [str(v) for v in json_obj.values() if v != 'Не указано']
                        return ' - '.join(values) if values else 'Не указано'
                        
            except (json.JSONDecodeError, TypeError):
                # Если это не валидный JSON, возвращаем как есть
                pass
                
            return json_str
        
        # Заменяем все JSON-объекты в тексте
        result = re.sub(json_pattern, replace_json_object, text)
        
        # Дополнительная обработка: удаляем лишние запятые между элементами списка
        result = re.sub(r'},\s*\{', '\n', result)
        result = re.sub(r'^\s*,\s*', '', result, flags=re.MULTILINE)
        
        return result
    
    async def _calculate_file_hash(self, file_path: str) -> str:
        """Вычислить хэш файла для кэширования"""
        import hashlib
        
        hash_obj = hashlib.sha256()
        
        # Читаем файл частями для больших файлов
        async with aiofiles.open(file_path, 'rb') as f:
            while chunk := await f.read(8192):
                hash_obj.update(chunk)
        
        return hash_obj.hexdigest()[:16]  # Берем первые 16 символов
    
    async def _cleanup_temp_file(self, file_path: str):
        """Асинхронная очистка временного файла"""
        try:
            await asyncio.sleep(1)  # Небольшая задержка
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.debug(f"Удален временный файл: {file_path}")
        except Exception as e:
            logger.warning(f"Не удалось удалить временный файл {file_path}: {e}")
    
    def _generate_result_cache_key(self, request: ProcessingRequest) -> str:
        """Генерировать ключ кэша для полного результата"""
        # Включаем все параметры, влияющие на результат
        key_data = {
            "file_id": request.file_id if not request.is_external_file else None,
            "file_path": request.file_path if request.is_external_file else None,
            "file_name": request.file_name,  # Добавляем имя файла для уникальности
            "template_id": request.template_id,
            "llm_provider": request.llm_provider,
            "language": request.language,
            "is_external_file": request.is_external_file
        }
        return performance_cache._generate_key("full_result", key_data)
    
    def _format_protocol(self, template: Any, llm_result: Any, 
                        transcription_result: Any) -> str:
        """Быстрое форматирование протокола"""
        # Используем кэшированное форматирование если возможно
        try:
            from jinja2 import Template as Jinja2Template
            
            # Получаем содержимое шаблона правильно
            if hasattr(template, 'content'):
                template_content = template.content
            elif isinstance(template, dict):
                template_content = template.get('content', '')
            else:
                template_content = str(template)
            
            jinja_template = Jinja2Template(template_content)
            return jinja_template.render(**llm_result)
        except Exception as e:
            logger.error(f"Ошибка форматирования протокола: {e}")
            # Fallback на простое форматирование
            return f"# Протокол\n\n{transcription_result.transcription}"
    
    async def get_performance_stats(self) -> Dict[str, Any]:
        """Получить статистику производительности"""
        cache_stats = performance_cache.get_stats()
        metrics_stats = metrics_collector.get_current_stats()
        task_pool_stats = task_pool.get_stats()
        
        return {
            "cache": cache_stats,
            "metrics": metrics_stats,
            "task_pool": task_pool_stats,
            "optimizations": {
                "transcription_cache_enabled": True,
                "llm_cache_enabled": True,
                "parallel_processing": True,
                "async_file_operations": True,
                "connection_pooling": True
            }
        }
    
    async def optimize_cache(self):
        """Оптимизация кэша"""
        # Очищаем просроченные записи
        await performance_cache.cleanup_expired()
        
        # Логируем статистику
        stats = performance_cache.get_stats()
        logger.info(f"Статистика кэша: hit_rate={stats['hit_rate_percent']}%, "
                   f"memory={stats['memory_usage_mb']}MB, "
                   f"entries={stats['memory_entries']+stats['disk_entries']}")
    
    async def _ensure_monitoring_started(self):
        """Безопасный запуск мониторинга"""
        if not self._monitoring_started:
            try:
                if not metrics_collector.is_monitoring:
                    metrics_collector.start_monitoring()
                    
                if not memory_optimizer.is_optimizing:
                    memory_optimizer.start_optimization()
                    
                self._monitoring_started = True
                logger.info("Мониторинг производительности запущен")
                
            except Exception as e:
                logger.warning(f"Не удалось запустить мониторинг: {e}")
                # Продолжаем работу без мониторинга
    
    def get_reliability_stats(self) -> Dict[str, Any]:
        """Получить статистику надежности"""
        try:
            # Получаем статистику из различных компонентов
            stats = {
                "performance_cache": {
                    "stats": performance_cache.get_stats() if hasattr(performance_cache, 'get_stats') else {}
                },
                "metrics": {
                    "collected": True if hasattr(metrics_collector, 'get_stats') else False
                },
                "thread_manager": {
                    "active": True if thread_manager else False
                },
                "optimizations": {
                    "async_enabled": True,
                    "cache_enabled": True,
                    "thread_pool_enabled": True
                }
            }
            
            return stats
        except Exception as e:
            logger.error(f"Ошибка при получении статистики надежности: {e}")
            return {"error": str(e), "status": "error"}


# Фабрика для создания оптимизированного сервиса
class OptimizedServiceFactory:
    """Фабрика для создания оптимизированных сервисов"""
    
    @staticmethod
    def create_processing_service() -> OptimizedProcessingService:
        """Создать оптимизированный сервис обработки"""
        return OptimizedProcessingService()
    
    @staticmethod
    async def create_with_prewarming() -> OptimizedProcessingService:
        """Создать сервис с предварительным прогревом"""
        service = OptimizedProcessingService()
        
        # Прогреваем кэш и системы
        await service._prewarm_systems()
        
        return service
    
    async def _prewarm_systems(self):
        """Предварительный прогрев систем"""
        logger.info("Прогрев оптимизированных систем...")
        
        # Прогреваем HTTP клиент
        async with OptimizedHTTPClient() as client:
            pass
        
        # Прогреваем thread pool
        await thread_manager.run_in_thread(lambda: True)
        
        logger.info("Системы прогреты и готовы к работе")
