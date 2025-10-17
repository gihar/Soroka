"""
Оптимизированный сервис обработки с улучшенной производительностью
"""

import asyncio
import time
import os
import aiofiles
from typing import Dict, Any, Optional
from loguru import logger

from src.services.base_processing_service import BaseProcessingService
from src.models.processing import ProcessingRequest, ProcessingResult
from src.exceptions.processing import ProcessingError
from src.performance.cache_system import performance_cache, cache_transcription, cache_llm_response
from src.performance.metrics import metrics_collector, PerformanceTimer, performance_timer
from src.performance.async_optimization import (
    task_pool, thread_manager, optimized_file_processing,
    OptimizedHTTPClient, async_lru_cache
)
from src.performance.memory_management import memory_optimizer
from reliability.middleware import monitoring_middleware
from database import db

# Новые сервисы для улучшения качества
from src.services.transcription_preprocessor import get_preprocessor
from src.services.diarization_analyzer import diarization_analyzer
from src.services.protocol_validator import protocol_validator
from src.services.segmentation_service import segmentation_service
from llm_providers import generate_protocol_two_stage, generate_protocol_chain_of_thought, llm_manager
from config import settings


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
        monitoring_start_time = time.time()

        def record_monitoring(success: bool) -> None:
            duration = (
                processing_metrics.total_duration
                if processing_metrics.total_duration
                else time.time() - monitoring_start_time
            )
            monitoring_middleware.record_protocol_request(
                user_id=request.user_id,
                duration=duration,
                success=success
            )
        
        try:
            # Начинаем отслеживание прогресса (первый видимый этап — "preparation")
            
            # Проверяем кэш полного результата
            cache_key = self._generate_result_cache_key(request)
            cached_result = await performance_cache.get(cache_key)
            
            if cached_result:
                logger.info(f"Найден кэшированный результат для {request.file_name}")
                processing_metrics.end_time = processing_metrics.start_time  # Мгновенный результат
                metrics_collector.finish_processing_metrics(processing_metrics)
                record_monitoring(True)
                await self._save_processing_history(request, cached_result)
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
            record_monitoring(True)
            await self._save_processing_history(request, result)
            return result
            
        except Exception as e:
            logger.error(f"Ошибка в оптимизированной обработке {request.file_name}: {e}")
            metrics_collector.finish_processing_metrics(processing_metrics, e)
            record_monitoring(False)
            raise

    async def _save_processing_history(
        self,
        request: ProcessingRequest,
        result: ProcessingResult
    ) -> None:
        """Сохранить информацию об успешной обработке в БД"""
        try:
            user = await self.user_service.get_user_by_telegram_id(request.user_id)
            if not user:
                logger.warning(
                    f"Не удалось сохранить историю обработки: пользователь {request.user_id} не найден"
                )
                return

            transcription_text = ""
            if getattr(result, "transcription_result", None):
                transcription_text = getattr(
                    result.transcription_result,
                    "transcription",
                    ""
                ) or ""

            await db.save_processing_result(
                user_id=user.id,
                file_name=request.file_name,
                template_id=request.template_id,
                llm_provider=result.llm_provider_used,
                transcription_text=transcription_text,
                result_text=result.protocol_text or ""
            )
        except Exception as err:
            logger.error(f"Ошибка при сохранении истории обработки: {err}")
    
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
            
            # Этап 1: Подготовка файла
            if progress_tracker:
                await progress_tracker.start_stage("preparation")
            
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
            
            # Этап 2: Транскрипция
            if progress_tracker:
                await progress_tracker.start_stage("transcription")
                
            transcription_result = await self._optimized_transcription(
                temp_file_path, request, processing_metrics, progress_tracker
            )
            
            # Этап 3: Анализ и генерация
            if progress_tracker:
                await progress_tracker.start_stage("analysis")
                
            llm_result = await self._optimized_llm_generation(
                transcription_result, template, request, processing_metrics
            )
            
            # Форматирование (включается в этап анализа)
            if progress_tracker:
                # Форматирование происходит в рамках этапа анализа
                pass
                
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
        """Оптимизированная транскрипция с кэшированием и предобработкой"""
        
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
            
            # Выполняем транскрипцию асинхронно
            logger.info(f"Запускаем транскрипцию файла: {file_path}")
            transcription_result = await self._run_transcription_async(
                file_path, request.language
            )
            logger.info(f"Транскрипция завершена. Результат получен: {hasattr(transcription_result, 'transcription')}")
            
            processing_metrics.transcription_duration = time.time() - start_time
            
            # Извлекаем метрики
            if hasattr(transcription_result, 'transcription'):
                processing_metrics.transcription_length = len(transcription_result.transcription)
            
            # Диаризация включается в этап транскрипции
            if hasattr(transcription_result, 'diarization') and transcription_result.diarization:
                diarization_data = transcription_result.diarization
                if isinstance(diarization_data, dict):
                    processing_metrics.speakers_count = diarization_data.get('total_speakers', 0)
                    processing_metrics.diarization_duration = 5.0  # Примерное время
        
        # Этап предобработки текста транскрипции
        if settings.enable_text_preprocessing and hasattr(transcription_result, 'transcription'):
            logger.info("Применение предобработки текста")
            preprocessor = get_preprocessor(request.language)
            
            preprocessed = preprocessor.preprocess(
                text=transcription_result.transcription,
                formatted_transcript=getattr(transcription_result, 'formatted_transcript', None)
            )
            
            # Обновляем транскрипцию очищенным текстом
            transcription_result.transcription = preprocessed['cleaned_text']
            if preprocessed['cleaned_formatted']:
                transcription_result.formatted_transcript = preprocessed['cleaned_formatted']
            
            logger.info(
                f"Предобработка завершена: сокращение на {preprocessed['statistics']['reduction_percent']}%"
            )
        
        # Этап расширенного анализа диаризации
        if settings.enable_diarization_analysis and hasattr(transcription_result, 'diarization'):
            if transcription_result.diarization:
                logger.info("Применение расширенного анализа диаризации")
                
                analysis_result = diarization_analyzer.enrich_diarization_data(
                    transcription_result.diarization,
                    transcription_result.transcription
                )
                
                # Сохраняем результат анализа
                transcription_result.diarization_analysis = analysis_result
                
                logger.info(
                    f"Анализ диаризации завершен: {analysis_result.total_speakers} спикеров, "
                    f"тип встречи: {analysis_result.meeting_type}"
                )
        
        # Кэшируем результат
        await performance_cache.set(cache_key, transcription_result, cache_type="transcription")
        
        return transcription_result
    
    async def _run_transcription_async(self, file_path: str, language: str):
        """Асинхронная транскрипция"""
        return await self.transcription_service.transcribe_with_diarization(
            file_path, language
        )
    
    @cache_llm_response()
    async def _optimized_llm_generation(self, transcription_result: Any, template: Dict,
                                      request: ProcessingRequest, processing_metrics) -> Any:
        """Оптимизированная генерация LLM с кэшированием, двухэтапным подходом и валидацией"""
        
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
            
            # Определяем ключ пресета модели OpenAI для текущего пользователя (если применимо)
            openai_model_key = None
            try:
                user = await self.user_service.get_user_by_telegram_id(request.user_id)
                if user and request.llm_provider == 'openai':
                    openai_model_key = getattr(user, 'preferred_openai_model_key', None)
            except Exception:
                openai_model_key = None
            
            # Извлекаем анализ диаризации если есть
            diarization_analysis = None
            if hasattr(transcription_result, 'diarization_analysis'):
                analysis_obj = transcription_result.diarization_analysis
                if analysis_obj:
                    # Если это уже словарь (из кэша), используем его напрямую
                    if isinstance(analysis_obj, dict):
                        diarization_analysis = analysis_obj
                    # Если это объект DiarizationAnalysisResult, вызываем to_dict()
                    elif hasattr(analysis_obj, 'to_dict'):
                        diarization_analysis = analysis_obj.to_dict()
            
            # Определяем длительность встречи для проверки необходимости Chain-of-Thought
            estimated_duration_minutes = None
            diarization_data_raw = getattr(transcription_result, 'diarization', None)
            if diarization_data_raw:
                estimated_duration_minutes = diarization_data_raw.get('total_duration', 0) / 60
            
            # Выбираем метод генерации: Chain-of-Thought > Двухэтапный > Стандартный
            # Проверяем необходимость Chain-of-Thought для длинных встреч
            should_use_cot = segmentation_service.should_use_segmentation(
                transcription=transcription_result.transcription,
                estimated_duration_minutes=estimated_duration_minutes
            )
            
            if should_use_cot and request.llm_provider == 'openai':
                logger.info("Использование Chain-of-Thought генерации для длинной встречи")
                
                # Сегментация транскрипции
                # Приоритет: по спикерам если есть диаризация, иначе по времени
                if diarization_data_raw and diarization_data_raw.get('formatted_transcript'):
                    logger.info("Сегментация по спикерам")
                    segments = segmentation_service.segment_by_speakers(
                        diarization_data=diarization_data_raw,
                        transcription=transcription_result.transcription
                    )
                else:
                    logger.info("Сегментация по времени")
                    segments = segmentation_service.segment_by_time(
                        transcription=transcription_result.transcription,
                        diarization_data=diarization_data_raw,
                        target_minutes=int(settings.chain_of_thought_threshold_minutes / 6)  # ~5 мин сегменты
                    )
                
                # Логирование сегментов
                for segment in segments:
                    logger.info(segmentation_service.create_segment_summary(segment))
                
                # Chain-of-Thought генерация
                llm_result_data = await generate_protocol_chain_of_thought(
                    manager=llm_manager,
                    provider_name=request.llm_provider,
                    transcription=transcription_result.transcription,
                    template_variables=template_variables,
                    segments=segments,
                    diarization_data=diarization_data_raw,
                    diarization_analysis=diarization_analysis,
                    openai_model_key=openai_model_key
                )
                
            elif settings.two_stage_processing and request.llm_provider == 'openai':
                logger.info("Использование двухэтапной генерации протокола")
                
                # Двухэтапная генерация
                llm_result_data = await generate_protocol_two_stage(
                    manager=llm_manager,
                    provider_name=request.llm_provider,
                    transcription=transcription_result.transcription,
                    template_variables=template_variables,
                    diarization_data=diarization_data_raw,
                    diarization_analysis=diarization_analysis,
                    openai_model_key=openai_model_key
                )
            else:
                # Стандартная генерация
                llm_task_id = f"llm_{request.user_id}_{int(time.time())}"
                
                llm_result = await task_pool.submit_task(
                    llm_task_id,
                    self._generate_llm_response,
                    transcription_result,
                    template,
                    template_variables,
                    request.llm_provider,
                    openai_model_key
                )
                
                if not llm_result.success:
                    raise ProcessingError(f"Ошибка LLM: {llm_result.error}", 
                                        request.file_name, "llm")
                
                llm_result_data = llm_result.result
            
            processing_metrics.llm_duration = time.time() - start_time
            
            # Валидация протокола
            if settings.enable_protocol_validation:
                logger.info("Запуск валидации протокола")
                
                validation_result = protocol_validator.calculate_quality_score(
                    protocol=llm_result_data,
                    transcription=transcription_result.transcription,
                    template_variables=template_variables,
                    diarization_data=getattr(transcription_result, 'diarization', None)
                )
                
                logger.info(
                    f"Валидация завершена: общая оценка {validation_result.overall_score}, "
                    f"полнота {validation_result.completeness_score}, "
                    f"структура {validation_result.structure_score}"
                )
                
                # Сохраняем результат валидации в метрики
                processing_metrics.protocol_quality_score = validation_result.overall_score
                
                # Если качество низкое, логируем предупреждения
                if validation_result.overall_score < 0.7:
                    logger.warning(
                        f"Низкое качество протокола ({validation_result.overall_score}). "
                        f"Предупреждения: {validation_result.warnings}"
                    )
                
                # Сохраняем валидацию в результате
                llm_result_data['_validation'] = validation_result.to_dict()
            
        # Кэшируем результат
        await performance_cache.set(cache_key, llm_result_data, cache_type="llm_response")
        
        return llm_result_data
    
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
                                   template_variables, llm_provider, openai_model_key=None):
        """Генерация ответа LLM с постобработкой"""
        llm_result = await self.llm_service.generate_protocol_with_fallback(
            llm_provider, transcription_result.transcription, template_variables,
            transcription_result.diarization if hasattr(transcription_result, 'diarization') else None,
            openai_model_key=openai_model_key
        )
        
        # Постобработка результатов - проверяем и исправляем неправильные JSON-структуры
        return self._post_process_llm_result(llm_result)
    
    def _post_process_llm_result(self, llm_result: Dict[str, Any]) -> Dict[str, Any]:
        """Постобработка результатов LLM для исправления JSON-структур в значениях"""
        if not isinstance(llm_result, dict):
            return llm_result
            
        processed_result = {}
        
        for key, value in llm_result.items():
            # Преобразуем сложные типы (dict, list) в читаемый текст
            processed_value = self._convert_complex_to_markdown(value)
            processed_result[key] = processed_value
        
        return processed_result
    
    def _convert_complex_to_markdown(self, value: Any) -> str:
        """Преобразовать сложные типы (dict, list) в читаемый Markdown-текст"""
        
        # Если уже строка - проверяем на JSON внутри и возвращаем
        if isinstance(value, str):
            return self._fix_json_in_text(value)
        
        # Преобразуем dict в текст
        if isinstance(value, dict):
            return self._format_dict_to_text(value)
        
        # Преобразуем list в текст
        if isinstance(value, list):
            return self._format_list_to_text(value)
        
        # Для остальных типов - просто строковое представление
        return str(value)
    
    def _format_dict_to_text(self, data: dict) -> str:
        """Форматировать словарь в читаемый текст"""
        
        # Специальные случаи для известных структур
        
        # Структура времени/даты с milestones, constraints
        if 'constraints' in data or 'milestones' in data or 'meetings' in data:
            parts = []
            if 'constraints' in data:
                constraints = data['constraints']
                if isinstance(constraints, list):
                    parts.append("Ограничения:\n" + "\n".join([f"- {c}" for c in constraints]))
            if 'milestones' in data:
                milestones = data['milestones']
                if isinstance(milestones, list):
                    milestone_texts = []
                    for m in milestones:
                        if isinstance(m, dict):
                            date = m.get('date', '')
                            event = m.get('event', '')
                            milestone_texts.append(f"- {date}: {event}")
                        else:
                            milestone_texts.append(f"- {m}")
                    parts.append("Важные даты:\n" + "\n".join(milestone_texts))
            if 'meetings' in data:
                meetings = data['meetings']
                if isinstance(meetings, list):
                    meeting_texts = []
                    for m in meetings:
                        if isinstance(m, dict):
                            slot = m.get('slot', '')
                            event = m.get('event', '')
                            meeting_texts.append(f"- {slot}: {event}")
                        else:
                            meeting_texts.append(f"- {m}")
                    parts.append("Встречи:\n" + "\n".join(meeting_texts))
            return "\n\n".join(parts) if parts else "Не указано"
        
        # Структура участника с name и role
        if 'name' in data and 'role' in data:
            name = data.get('name', '')
            role = data.get('role', '')
            notes = data.get('notes', '')
            if notes:
                return f"{name} ({role}): {notes}"
            return f"{name} ({role})" if role else name
        
        # Структура решения с decision
        if 'decision' in data:
            decision = data.get('decision', '')
            decision_maker = data.get('decision_maker', '')
            if decision_maker and decision_maker != 'Не указано':
                return f"- {decision} (решение принял: {decision_maker})"
            return f"- {decision}"
        
        # Структура задачи с item
        if 'item' in data or 'task' in data:
            item = data.get('item', data.get('task', ''))
            assignee = data.get('assignee', 'Не указано')
            due = data.get('due', '')
            if due:
                return f"- {item} — Ответственный: {assignee}, срок: {due}"
            return f"- {item} — Ответственный: {assignee}"
        
        # Общий случай - key: value пары
        lines = []
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                v_str = self._convert_complex_to_markdown(v)
                lines.append(f"**{k}:** {v_str}")
            else:
                lines.append(f"**{k}:** {v}")
        return "\n".join(lines) if lines else "Не указано"
    
    def _format_list_to_text(self, data: list) -> str:
        """Форматировать список в читаемый текст"""
        if not data:
            return "Не указано"
        
        # Проверяем тип первого элемента
        first = data[0]
        
        # Список словарей - обрабатываем каждый
        if isinstance(first, dict):
            items = []
            for item in data:
                formatted = self._format_dict_to_text(item)
                # Если результат уже с дефисом, не добавляем еще один
                if formatted.strip().startswith('-'):
                    items.append(formatted.strip())
                else:
                    items.append(f"- {formatted}")
            return "\n".join(items)
        
        # Список простых значений
        return "\n".join([f"- {item}" for item in data])
    
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
        """Форматирование протокола с мягкой обработкой типов результата LLM"""
        from jinja2 import Template as Jinja2Template
        
        # Если LLM вернул строку — считаем это готовым текстом протокола
        if isinstance(llm_result, str):
            text = llm_result.strip()
            if text:
                return text
            # Пустая строка — падаем на простой формат
            return f"# Протокол\n\n{transcription_result.transcription}"
        
        # Получаем содержимое шаблона
        if hasattr(template, 'content'):
            template_content = template.content
        elif isinstance(template, dict):
            template_content = template.get('content', '')
        else:
            template_content = str(template)
        
        # Если есть маппинг — используем Jinja2 для подстановки
        try:
            if isinstance(llm_result, dict):
                jinja_template = Jinja2Template(template_content)
                return jinja_template.render(**llm_result)
        except Exception as e:
            logger.warning(f"Ошибка Jinja при форматировании протокола: {e}")
        
        # Fallback: возвращаем базовый текст транскрипции
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
