"""
Оптимизированный сервис обработки с улучшенной производительностью
"""

import asyncio
import time
import os
import json
import aiofiles
from typing import Dict, Any, Optional
from datetime import datetime
from uuid import uuid4
from loguru import logger

from src.services.base_processing_service import BaseProcessingService
from src.models.processing import ProcessingRequest, ProcessingResult
from src.exceptions.processing import ProcessingError
from src.performance.cache_system import performance_cache, cache_transcription, cache_llm_response
from src.performance.metrics import metrics_collector, PerformanceTimer, performance_timer, ProcessingMetrics
from src.performance.async_optimization import (
    task_pool, thread_manager, optimized_file_processing,
    OptimizedHTTPClient
)
from src.performance.memory_management import memory_optimizer
from src.reliability.middleware import monitoring_middleware
from database import db
from src.utils.telegram_safe import safe_send_message

# Новые сервисы для улучшения качества
from src.services.transcription_preprocessor import get_preprocessor
from src.services.diarization_analyzer import diarization_analyzer
from src.services.protocol_validator import protocol_validator


from src.services.smart_template_selector import smart_selector
from llm_providers import llm_manager
from config import settings


class ProcessingService(BaseProcessingService):
    """Сервис обработки с оптимизацией производительности"""
    
    def __init__(self):
        super().__init__()
        
        # Мониторинг будет запущен при первом использовании
        self._monitoring_started = False
    
    def _format_speaker_mapping_message(
        self,
        speaker_mapping: Dict[str, str],
        total_participants: int
    ) -> str:
        """
        Форматирует сообщение о результатах сопоставления спикеров
        
        Args:
            speaker_mapping: Словарь сопоставления {speaker_id: participant_name}
            total_participants: Общее количество участников
            
        Returns:
            Отформатированное сообщение для отправки пользователю
        """
        if not speaker_mapping:
            return (
                "ℹ️ *Автоматическое сопоставление участников не выполнено*\n\n"
                "Протокол будет сформирован без привязки спикеров к именам участников."
            )
        
        mapped_count = len(speaker_mapping)
        message = "✅ *Сопоставление участников завершено*\n\n"
        message += f"Сопоставлено {mapped_count} из {total_participants} участников:\n\n"
        
        # Сортируем по speaker_id для предсказуемого порядка
        sorted_mapping = sorted(speaker_mapping.items())
        
        for speaker_id, participant_name in sorted_mapping:
            message += f"• {speaker_id} -> {participant_name}\n"
        
        return message.rstrip()
    
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
        
        temp_file_path = None
        cache_check_only = False  # Флаг, что файл скачан только для проверки кеша
        
        try:
            # Шаг 1: Получаем путь к файлу (скачиваем или используем существующий)
            if request.is_external_file:
                # Для внешних файлов путь уже указан
                temp_file_path = request.file_path
                if not os.path.exists(temp_file_path):
                    raise ProcessingError(
                        f"Файл не найден: {temp_file_path}", 
                        request.file_name, 
                        "file_preparation"
                    )
            else:
                # Для Telegram файлов - скачиваем
                temp_file_path = await self._download_telegram_file(request)
                cache_check_only = True  # Отметим, что файл скачан специально для проверки кеша
            
            # Шаг 2: Вычисляем хеш файла
            file_hash = await self._calculate_file_hash(temp_file_path)
            logger.debug(f"Вычислен хеш файла: {file_hash}")
            
            # Шаг 3: Генерируем ключ кеша с хешем
            cache_key = self._generate_result_cache_key(request, file_hash)
            
            # Шаг 4: Проверяем кэш полного результата
            cached_result = await performance_cache.get(cache_key)
            
            if cached_result:
                logger.info(f"✅ Найден кэшированный результат для {request.file_name} (file_hash: {file_hash})")
                processing_metrics.end_time = processing_metrics.start_time  # Мгновенный результат
                metrics_collector.finish_processing_metrics(processing_metrics)
                record_monitoring(True)
                await self._save_processing_history(request, cached_result)
                if progress_tracker:
                    await progress_tracker.complete_all()
                
                # Если файл был скачан только для проверки кеша - удаляем его
                if cache_check_only and temp_file_path and os.path.exists(temp_file_path):
                    await self._cleanup_temp_file(temp_file_path)
                
                return cached_result
            
            logger.info(f"❌ Кеш не найден для {request.file_name} (file_hash: {file_hash}), начинаем обработку")
            cache_check_only = False  # Файл будет использован для обработки
            
            # Шаг 5: Если кэша нет, выполняем оптимизированную обработку
            result = await self._process_file_optimized(request, processing_metrics, progress_tracker, temp_file_path)
            
            # Проверяем, была ли обработка приостановлена для подтверждения сопоставления
            if result is None:
                logger.info("⏸️ Обработка приостановлена - ожидаю подтверждения от пользователя")
                # Не сохраняем в кеш и не завершаем метрики - это будет сделано после подтверждения
                return None
            
            # Шаг 6: Кэшируем результат
            await performance_cache.set(
                cache_key, result, 
                cache_type="processing_result"
            )
            logger.info(f"💾 Результат закеширован для {request.file_name} (file_hash: {file_hash})")
            
            metrics_collector.finish_processing_metrics(processing_metrics)
            record_monitoring(True)
            await self._save_processing_history(request, result)
            return result
            
        except Exception as e:
            logger.error(f"Ошибка в оптимизированной обработке {request.file_name}: {e}")
            metrics_collector.finish_processing_metrics(processing_metrics, e)
            record_monitoring(False)
            # Если файл был скачан только для проверки кеша - удаляем его
            if cache_check_only and temp_file_path and os.path.exists(temp_file_path):
                await self._cleanup_temp_file(temp_file_path)
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
                                    processing_metrics, progress_tracker=None, 
                                    temp_file_path: str = None) -> ProcessingResult:
        """Внутренняя оптимизированная обработка
        
        Args:
            request: Запрос на обработку
            processing_metrics: Метрики производительности
            progress_tracker: Трекер прогресса
            temp_file_path: Путь к уже скачанному файлу (если None, файл будет скачан)
        """
        
        # ДОБАВЛЕНО: Логирование данных из ProcessingRequest для диагностики
        logger.info(f"🔍 Данные из ProcessingRequest при начале обработки:")
        if request.participants_list:
            logger.info(f"  participants_list: {len(request.participants_list)} чел.")
            # Показываем первые 3 участника для проверки
            for i, p in enumerate(request.participants_list[:3], 1):
                logger.info(f"    {i}. {p.get('name')} ({p.get('role', 'без роли')})")
            if len(request.participants_list) > 3:
                logger.info(f"    ... и еще {len(request.participants_list) - 3} участников")
        else:
            logger.warning("  participants_list: None (НЕ ПЕРЕДАН В REQUEST!)")
        logger.info(f"  meeting_topic: {request.meeting_topic}")
        logger.info(f"  meeting_date: {request.meeting_date}")
        logger.info(f"  meeting_time: {request.meeting_time}")
        logger.info(f"  speaker_mapping: {request.speaker_mapping}")
        
        async with optimized_file_processing() as resources:
            http_client = resources["http_client"]
            
            # Этап 1: Загрузка данных пользователя
            with PerformanceTimer("data_loading", metrics_collector):
                user = await self.user_service.get_user_by_telegram_id(request.user_id)
                
                if not user:
                    raise ProcessingError(f"Пользователь {request.user_id} не найден", 
                                        request.file_name, "validation")
            
            processing_metrics.validation_duration = 0.5  # Примерное время
            
            # Этап 1: Подготовка файла
            if progress_tracker:
                await progress_tracker.start_stage("preparation")
            
            with PerformanceTimer("file_download", metrics_collector):
                # Если путь к файлу не передан, скачиваем файл
                if temp_file_path is None:
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
                            error_msg = download_result.get('error', 'Неизвестная ошибка скачивания')
                            raise ProcessingError(f"Ошибка скачивания: {error_msg}", 
                                                request.file_name, "download")
                        
                        processing_metrics.download_duration = download_result["duration"]
                        processing_metrics.file_size_bytes = download_result["bytes_downloaded"]
                else:
                    # Файл уже скачан, просто получаем метрики
                    if os.path.exists(temp_file_path):
                        file_size = os.path.getsize(temp_file_path)
                        processing_metrics.file_size_bytes = file_size
                        processing_metrics.download_duration = 0.0  # Файл уже был скачан ранее
                        logger.debug(f"Используем уже скачанный файл: {temp_file_path} ({file_size} байт)")
                    else:
                        raise ProcessingError(f"Файл не найден: {temp_file_path}", 
                                            request.file_name, "file_preparation")
                
                processing_metrics.file_format = os.path.splitext(request.file_name)[1]
            
            # Этап 2: Транскрипция
            if progress_tracker:
                await progress_tracker.start_stage("transcription")
                
            transcription_result = await self._optimized_transcription(
                temp_file_path, request, processing_metrics, progress_tracker
            )
            
            # Этап 2.3: Сопоставление спикеров с участниками (если указан список)
            # КРИТИЧЕСКИ ВАЖНО: логируем состояние для диагностики
            logger.info(f"Проверка условий для speaker mapping: participants_list={request.participants_list is not None} ({len(request.participants_list) if request.participants_list else 0} чел.), diarization={transcription_result.diarization is not None}")
            
            # Инициализируем переменную для типа встречи
            request_meeting_type = None
            
            if request.participants_list and transcription_result.diarization:
                # Пропускаем обновление статуса, так как это быстрая операция
                # и не требует отдельного отображения в трекере прогресса
                
                try:
                    from src.services.speaker_mapping_service import speaker_mapping_service
                    
                    logger.info(f"🎭 НАЧАЛО СОПОСТАВЛЕНИЯ СПИКЕРОВ И ОПРЕДЕЛЕНИЯ ТИПА ВСТРЕЧИ: {len(request.participants_list)} участников")
                    logger.info(f"Список участников для сопоставления:")
                    for i, p in enumerate(request.participants_list[:5], 1):  # Показываем первые 5
                        logger.info(f"  {i}. {p.get('name')} ({p.get('role', 'без роли')})")
                    if len(request.participants_list) > 5:
                        logger.info(f"  ... и еще {len(request.participants_list) - 5} участников")
                    
                    speaker_mapping, meeting_type = await speaker_mapping_service.map_speakers_to_participants(
                        diarization_data=transcription_result.diarization,
                        participants=request.participants_list,
                        transcription_text=transcription_result.transcription,
                        llm_provider=request.llm_provider
                    )
                    
                    logger.info(f"✅ СОПОСТАВЛЕНИЕ ЗАВЕРШЕНО: {len(speaker_mapping)} спикеров сопоставлено, тип встречи: {meeting_type}")
                    if speaker_mapping:
                        logger.info("Результаты сопоставления:")
                        for speaker_id, name in speaker_mapping.items():
                            logger.info(f"  {speaker_id} → {name}")
                    else:
                        logger.warning("⚠️ Speaker mapping вернул пустой результат - протокол будет генерироваться без сопоставления спикеров")
                    
                    # Проверяем, нужно ли показывать UI подтверждения
                    if settings.enable_speaker_mapping_confirmation:
                        logger.info("🔄 UI подтверждения сопоставления включен - сохраняю состояние и показываю интерфейс")
                        
                        # Сохраняем состояние в кеш
                        from src.services.mapping_state_cache import mapping_state_cache
                        await mapping_state_cache.save_state(request.user_id, {
                            'speaker_mapping': speaker_mapping,
                            'meeting_type': meeting_type,  # Сохраняем тип встречи
                            'diarization_data': transcription_result.diarization,
                            'participants_list': request.participants_list,
                            'request_data': request.model_dump() if hasattr(request, 'model_dump') else request.dict(),
                            'transcription_result': {
                                'transcription': transcription_result.transcription,
                                'formatted_transcript': transcription_result.formatted_transcript,
                                'speakers_text': transcription_result.speakers_text,
                                'speakers_summary': transcription_result.speakers_summary
                            },
                            'temp_file_path': temp_file_path,
                            'processing_metrics': {
                                'start_time': processing_metrics.start_time.isoformat() if hasattr(processing_metrics, 'start_time') else datetime.now().isoformat(),
                                'total_duration': processing_metrics.total_duration if hasattr(processing_metrics, 'total_duration') else 0,
                                'download_duration': processing_metrics.download_duration if hasattr(processing_metrics, 'download_duration') else 0,
                                'validation_duration': processing_metrics.validation_duration if hasattr(processing_metrics, 'validation_duration') else 0,
                                'conversion_duration': processing_metrics.conversion_duration if hasattr(processing_metrics, 'conversion_duration') else 0,
                                'transcription_duration': processing_metrics.transcription_duration if hasattr(processing_metrics, 'transcription_duration') else 0,
                                'diarization_duration': processing_metrics.diarization_duration if hasattr(processing_metrics, 'diarization_duration') else 0
                            }
                        })
                        
                    # Показываем UI подтверждения
                    if progress_tracker:
                        from src.ux.speaker_mapping_ui import show_mapping_confirmation
                        
                        # Останавливаем автообновления progress_tracker, чтобы избежать преждевременного "Обработка завершена!"
                        if progress_tracker.update_task:
                            task = progress_tracker.update_task
                            progress_tracker.update_task = None
                            task.cancel()
                            try:
                                await task
                            except asyncio.CancelledError:
                                pass
                            logger.debug("🛑 Автообновления progress_tracker остановлены перед показом UI подтверждения")
                        
                        # Обновляем сообщение progress_tracker на информационное (БЕЗ final=True)
                        try:
                            from src.utils.telegram_safe import safe_edit_text
                            await safe_edit_text(
                                progress_tracker.message,
                                "✅ **Транскрипция завершена**\n\n"
                                "🎭 Проверьте сопоставление спикеров с участниками в сообщении ниже.",
                                parse_mode="Markdown"
                            )
                            logger.debug("✅ Сообщение progress_tracker обновлено на информационное")
                        except Exception as e:
                            logger.warning(f"Не удалось обновить сообщение progress_tracker: {e}")
                        
                        # Получаем список несопоставленных спикеров
                        all_speakers = transcription_result.diarization.get('speakers', [])
                        if not all_speakers:
                            segments = transcription_result.diarization.get('segments', [])
                            all_speakers = sorted(set(s.get('speaker') for s in segments if s.get('speaker')))
                        mapped_speakers = set(speaker_mapping.keys())
                        unmapped_speakers = [s for s in all_speakers if s not in mapped_speakers]
                        
                        # Извлекаем speakers_text для передачи в UI
                        speakers_text = transcription_result.speakers_text
                        
                        # Пытаемся показать UI подтверждения
                        confirmation_message = await show_mapping_confirmation(
                            bot=progress_tracker.bot,
                            chat_id=progress_tracker.chat_id,
                            user_id=request.user_id,
                            speaker_mapping=speaker_mapping,
                            diarization_data=transcription_result.diarization,
                            participants=request.participants_list,
                            unmapped_speakers=unmapped_speakers if unmapped_speakers else None,
                            speakers_text=speakers_text
                        )
                        
                        # Проверяем, удалось ли отправить UI
                        if confirmation_message is None:
                            # UI не был отправлен - продолжаем обработку без паузы
                            logger.warning(
                                f"⚠️ Не удалось отправить UI подтверждения сопоставления для пользователя {request.user_id}. "
                                "Продолжаю обработку без паузы на подтверждение."
                            )
                            
                            # Отправляем уведомление пользователю
                            try:
                                from src.utils.telegram_safe import safe_send_message
                                await safe_send_message(
                                    bot=progress_tracker.bot,
                                    chat_id=progress_tracker.chat_id,
                                    text=(
                                        "⚠️ Не удалось отправить интерфейс подтверждения сопоставления.\n\n"
                                        "Продолжаю генерацию протокола с автоматическим сопоставлением спикеров."
                                    ),
                                    parse_mode=None
                                )
                            except Exception as notify_error:
                                logger.error(f"Не удалось отправить уведомление об ошибке UI: {notify_error}")
                            
                            # Очищаем кеш состояния, так как обработка продолжается без паузы
                            from src.services.mapping_state_cache import mapping_state_cache
                            await mapping_state_cache.clear_state(request.user_id)
                            
                            # Продолжаем обработку без паузы - сохраняем mapping в request
                            request.speaker_mapping = speaker_mapping
                        else:
                            # UI успешно отправлен - приостанавливаем обработку
                            logger.info("⏸️ Обработка приостановлена - ожидаю подтверждения от пользователя")
                            
                            # Возвращаем None как индикатор паузы (обработка продолжится после подтверждения)
                            return None
                    else:
                        logger.warning("⚠️ UI подтверждения включен, но progress_tracker отсутствует - продолжаю без паузы")
                    
                    # Сохраняем mapping в request для дальнейшего использования (если UI не включен)
                    request.speaker_mapping = speaker_mapping
                    # Сохраняем meeting_type для передачи в генерацию протокола
                    request_meeting_type = meeting_type
                    
                    # ЗАКОММЕНТИРОВАНО: Промежуточное уведомление больше не отправляется
                    # Информация о сопоставлении будет показана в финальном сообщении с протоколом
                    # if progress_tracker:
                    #     try:
                    #         from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                    #         import json
                    #         
                    #         notification_text = self._format_speaker_mapping_message(
                    #             speaker_mapping,
                    #             len(request.participants_list)
                    #         )
                    #         
                    #         # Создаем клавиатуру с кнопками действий
                    #         keyboard_buttons = []
                    #         
                    #         # Если есть хотя бы одно сопоставление, добавляем кнопку редактирования
                    #         if speaker_mapping:
                    #             # Сохраняем данные для callback (ограничим размер)
                    #             callback_data = {
                    #                 "action": "edit_mapping",
                    #                 "task_id": str(request.user_id)  # Используем user_id как идентификатор
                    #             }
                    #             keyboard_buttons.append([InlineKeyboardButton(
                    #                 text="✏️ Изменить сопоставление",
                    #                 callback_data=f"edit_mapping:{request.user_id}"
                    #             )])
                    #         
                    #         # Кнопка продолжения (всегда доступна)
                    #         keyboard_buttons.append([InlineKeyboardButton(
                    #             text="✅ Продолжить с текущим",
                    #             callback_data=f"continue_mapping:{request.user_id}"
                    #         )])
                    #         
                    #         keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons) if keyboard_buttons else None
                    #         
                    #         await safe_send_message(
                    #             progress_tracker.bot,
                    #             progress_tracker.chat_id,
                    #             notification_text,
                    #             parse_mode="Markdown",
                    #             reply_markup=keyboard
                    #         )
                    #         logger.debug("Уведомление о сопоставлении отправлено пользователю")
                    #     except Exception as notify_error:
                    #         logger.warning(f"Не удалось отправить уведомление о сопоставлении: {notify_error}")
                    
                except Exception as e:
                    logger.error(f"❌ ОШИБКА ПРИ СОПОСТАВЛЕНИИ СПИКЕРОВ: {e}", exc_info=True)
                    # Продолжаем без mapping
                    request.speaker_mapping = None
            else:
                if not request.participants_list:
                    logger.info("ℹ️ Speaker mapping пропущен: список участников не предоставлен")
                elif not transcription_result.diarization:
                    logger.warning("⚠️ Speaker mapping пропущен: диаризация не выполнена")
                request.speaker_mapping = None
            
            # Этап 2.5: Умный выбор шаблона после транскрипции
            template = await self._suggest_template_if_needed(
                request, transcription_result, progress_tracker
            )
            
            if not template:
                raise ProcessingError("Не удалось выбрать шаблон", 
                                    request.file_name, "template_selection")
            
            # Обновляем request с выбранным шаблоном
            request.template_id = template.id
            
            # Этап 3: Анализ и генерация
            if progress_tracker:
                await progress_tracker.start_stage("analysis")
                
            llm_result = await self._optimized_llm_generation(
                transcription_result, template, request, processing_metrics, meeting_type=request_meeting_type
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
                
                # Применяем замену спикеров на реальные имена
                if request.speaker_mapping:
                    from src.utils.text_processing import replace_speakers_in_text
                    protocol_text = replace_speakers_in_text(protocol_text, request.speaker_mapping)
                    logger.info(f"Применена замена спикеров на имена участников")
            
            # Очистка временного файла в фоне (только для внешних файлов)
            if request.is_external_file:
                asyncio.create_task(self._cleanup_temp_file(temp_file_path))
            
            # Определяем название модели для результата
            openai_model_key = None
            if request.llm_provider == 'openai':
                openai_model_key = getattr(user, 'preferred_openai_model_key', None)
            llm_model_display_name = self._get_model_display_name(request.llm_provider, openai_model_key)
            
            # Создаем результат
            return ProcessingResult(
                transcription_result=transcription_result,
                protocol_text=protocol_text,
                template_used=template.model_dump() if hasattr(template, 'model_dump') else template.__dict__,
                llm_provider_used=request.llm_provider,
                llm_model_used=llm_model_display_name,
                processing_duration=processing_metrics.total_duration
            )
    
    async def continue_processing_after_mapping_confirmation(
        self,
        user_id: int,
        confirmed_mapping: Dict[str, str],
        bot: Any,
        chat_id: int
    ) -> ProcessingResult:
        """
        Продолжить обработку после подтверждения сопоставления спикеров
        
        Args:
            user_id: ID пользователя
            confirmed_mapping: Подтвержденное сопоставление спикеров
            bot: Экземпляр бота для отправки сообщений
            chat_id: ID чата
            
        Returns:
            ProcessingResult с готовым протоколом
        """
        from src.services.mapping_state_cache import mapping_state_cache
        from src.models.processing import ProcessingRequest, TranscriptionResult
        from src.ux.progress_tracker import ProgressFactory
        
        try:
            logger.info(f"🔄 Продолжение обработки для пользователя {user_id} после подтверждения сопоставления")
            
            # Загружаем сохраненное состояние
            state_data = await mapping_state_cache.load_state(user_id)
            
            if not state_data:
                raise ProcessingError(
                    "Состояние обработки не найдено или истекло",
                    "unknown",
                    "state_expired"
                )
            
            # Восстанавливаем данные из состояния
            request_data = state_data.get('request_data', {})
            transcription_data = state_data.get('transcription_result', {})
            diarization_data = state_data.get('diarization_data', {})
            temp_file_path = state_data.get('temp_file_path')
            meeting_type = state_data.get('meeting_type', 'general')  # Извлекаем тип встречи
            
            logger.info(f"📋 Восстановлено из кеша: тип встречи = {meeting_type}")
            
            # Восстанавливаем ProcessingRequest
            request = ProcessingRequest(**request_data)
            request.speaker_mapping = confirmed_mapping
            
            # Восстанавливаем TranscriptionResult
            transcription_result = TranscriptionResult(
                transcription=transcription_data.get('transcription', ''),
                diarization=diarization_data,
                speakers_text=transcription_data.get('speakers_text', {}),
                formatted_transcript=transcription_data.get('formatted_transcript', ''),
                speakers_summary=transcription_data.get('speakers_summary', '')
            )
            
            # Создаем новый progress tracker для продолжения
            progress_tracker = await ProgressFactory.create_file_processing_tracker(
                bot=bot,
                chat_id=chat_id
            )
            
            # Создаем метрики (восстанавливаем из сохраненного состояния)
            saved_metrics = state_data.get('processing_metrics', {})
            processing_metrics = ProcessingMetrics(
                file_name=request.file_name,
                user_id=user_id,
                start_time=datetime.fromisoformat(saved_metrics['start_time']) if saved_metrics.get('start_time') else datetime.now()
            )
            # Восстанавливаем длительность этапов, если они были сохранены
            if 'download_duration' in saved_metrics:
                processing_metrics.download_duration = saved_metrics['download_duration']
            if 'validation_duration' in saved_metrics:
                processing_metrics.validation_duration = saved_metrics['validation_duration']
            if 'conversion_duration' in saved_metrics:
                processing_metrics.conversion_duration = saved_metrics['conversion_duration']
            if 'transcription_duration' in saved_metrics:
                processing_metrics.transcription_duration = saved_metrics['transcription_duration']
            if 'diarization_duration' in saved_metrics:
                processing_metrics.diarization_duration = saved_metrics['diarization_duration']
            
            # Продолжаем с этапа выбора шаблона (если еще не выбран)
            if not request.template_id:
                template = await self._suggest_template_if_needed(
                    request, transcription_result, progress_tracker
                )
                if not template:
                    raise ProcessingError(
                        "Не удалось выбрать шаблон",
                        request.file_name,
                        "template_selection"
                    )
                request.template_id = template.id
            else:
                template = await self.template_service.get_template_by_id(request.template_id)
                if not template:
                    raise ProcessingError(
                        f"Шаблон с ID {request.template_id} не найден",
                        request.file_name,
                        "template_not_found"
                    )
            
            # Этап 3: Анализ и генерация
            if progress_tracker:
                await progress_tracker.start_stage("analysis")
            
            logger.info(f"🔄 Начинаем генерацию протокола для пользователя {user_id}")
            
            llm_result = await self._optimized_llm_generation(
                transcription_result, template, request, processing_metrics,
                meeting_type=meeting_type
            )
            
            # Проверяем результат LLM на корректность
            logger.info(f"✅ LLM генерация завершена. Тип результата: {type(llm_result)}")
            if llm_result is None:
                raise ProcessingError(
                    "LLM вернул пустой результат",
                    request.file_name,
                    "llm_empty_result"
                )
            
            # Форматирование
            with PerformanceTimer("formatting", metrics_collector):
                processing_metrics.formatting_duration = 0.1
                
                logger.info(f"🔄 Форматирование протокола...")
                try:
                    protocol_text = self._format_protocol(
                        template, llm_result, transcription_result
                    )
                    logger.info(f"✅ Протокол отформатирован. Длина: {len(protocol_text)} символов")
                except Exception as format_error:
                    logger.error(f"❌ Ошибка форматирования протокола: {format_error}")
                    logger.error(f"Тип llm_result: {type(llm_result)}")
                    logger.error(f"Содержимое llm_result (первые 500 символов): {str(llm_result)[:500]}")
                    raise ProcessingError(
                        f"Ошибка форматирования протокола: {str(format_error)}",
                        request.file_name,
                        "protocol_formatting_error"
                    )
                
                # Применяем замену спикеров на реальные имена
                if confirmed_mapping:
                    from src.utils.text_processing import replace_speakers_in_text
                    protocol_text = replace_speakers_in_text(protocol_text, confirmed_mapping)
                    logger.info(f"Применена замена спикеров на имена участников (подтвержденное сопоставление)")
            
            # Очистка временного файла в фоне (только для внешних файлов)
            if request.is_external_file and temp_file_path:
                asyncio.create_task(self._cleanup_temp_file(temp_file_path))
            
            # Определяем название модели для результата
            user = await self.user_service.get_user_by_telegram_id(user_id)
            openai_model_key = None
            if request.llm_provider == 'openai' and user:
                openai_model_key = getattr(user, 'preferred_openai_model_key', None)
            llm_model_display_name = self._get_model_display_name(request.llm_provider, openai_model_key)
            
            # Создаем результат
            result = ProcessingResult(
                transcription_result=transcription_result,
                protocol_text=protocol_text,
                template_used=template.model_dump() if hasattr(template, 'model_dump') else template.__dict__,
                llm_provider_used=request.llm_provider,
                llm_model_used=llm_model_display_name,
                processing_duration=processing_metrics.total_duration
            )
            
            # Отправляем результат пользователю (используем тот же подход, что и в task_queue_manager)
            from src.services.task_queue_manager import TaskQueueManager
            from src.models.task_queue import QueuedTask, TaskPriority
            
            task_queue_manager = TaskQueueManager()
            
            # Создаем фиктивный QueuedTask для отправки результата
            # (нам нужна только структура для _send_result_to_user)
            fake_task = QueuedTask(
                task_id=uuid4(),
                request=request,
                user_id=user_id,
                chat_id=chat_id,
                priority=TaskPriority.NORMAL,
                created_at=datetime.now()
            )
            
            await task_queue_manager._send_result_to_user(
                bot=bot,
                task=fake_task,
                result=result,
                progress_tracker=progress_tracker
            )
            
            # Сохраняем историю обработки
            await self._save_processing_history(request, result)
            
            logger.info(f"✅ Обработка успешно завершена для пользователя {user_id}")
            
            return result
            
        except ProcessingError as e:
            # Критичная ошибка обработки (состояние истекло, шаблон не найден и т.д.)
            # Экранируем фигурные скобки в сообщении об ошибке для безопасного логирования
            error_msg_safe = str(e).replace('{', '{{').replace('}', '}}')
            logger.error(f"❌ Критичная ошибка обработки для пользователя {user_id}: {error_msg_safe}", exc_info=True)
            
            # Очищаем состояние при критичной ошибке
            await mapping_state_cache.clear_state(user_id)
            
            # Отправляем сообщение об ошибке
            await safe_send_message(
                bot=bot,
                chat_id=chat_id,
                text=f"❌ Произошла критичная ошибка:\n\n{str(e)}\n\n"
                     f"Пожалуйста, начните обработку заново."
            )
            
            raise
            
        except json.JSONDecodeError as e:
            # Некритичная ошибка парсинга JSON - НЕ очищаем состояние
            error_msg = f"Ошибка парсинга JSON: {str(e)}"
            
            # Расширенное логирование с контекстом
            logger.error(f"⚠️ Некритичная ошибка парсинга JSON для пользователя {user_id}")
            logger.error(f"Детали ошибки: {error_msg}")
            
            # Логируем контекст из состояния если доступен
            try:
                state_data = await mapping_state_cache.load_state(user_id)
                if state_data:
                    request_data = state_data.get('request_data', {})
                    logger.error(f"Контекст обработки:")
                    logger.error(f"  - LLM провайдер: {request_data.get('llm_provider', 'unknown')}")
                    logger.error(f"  - Шаблон ID: {request_data.get('template_id', 'unknown')}")
                    logger.error(f"  - Файл: {request_data.get('file_name', 'unknown')}")
                    logger.error(f"  - Участники: {len(request_data.get('participants_list', []))} чел.")
            except Exception as log_error:
                logger.warning(f"Не удалось получить контекст из состояния: {log_error}")
            
            # Логируем полный traceback
            logger.error("Полный traceback:", exc_info=True)
            
            # НЕ очищаем состояние - пользователь может повторить попытку
            
            # Отправляем сообщение с предложением повторить
            await safe_send_message(
                bot=bot,
                chat_id=chat_id,
                text=f"⚠️ Произошла временная ошибка при обработке:\n\n{error_msg}\n\n"
                     f"Это может быть связано с проблемами API. "
                     f"Ваше состояние сохранено - вы можете повторить попытку через кнопку подтверждения."
            )
            
            raise ProcessingError(
                f"Ошибка парсинга ответа: {str(e)}",
                "unknown",
                "json_parse_error"
            )
            
        except (TimeoutError, asyncio.TimeoutError) as e:
            # Timeout - НЕ очищаем состояние
            error_msg = "Превышено время ожидания ответа от сервиса"
            # Экранируем фигурные скобки в сообщении об ошибке для безопасного логирования
            error_msg_safe = str(e).replace('{', '{{').replace('}', '}}')
            logger.error(f"⚠️ Timeout для пользователя {user_id}: {error_msg_safe}", exc_info=True)
            
            # НЕ очищаем состояние - пользователь может повторить попытку
            
            await safe_send_message(
                bot=bot,
                chat_id=chat_id,
                text=f"⚠️ {error_msg}\n\n"
                     f"Ваше состояние сохранено - попробуйте повторить через минуту."
            )
            
            raise ProcessingError(
                error_msg,
                "unknown",
                "timeout_error"
            )
            
        except Exception as e:
            # Неизвестная ошибка - определяем, критична ли она
            import traceback
            
            error_type = type(e).__name__
            error_msg = str(e).lower() if e else "unknown error"
            
            # Детальное логирование для диагностики
            logger.error(f"❌ Неожиданное исключение в continue_processing_after_mapping_confirmation")
            logger.error(f"Тип ошибки: {error_type}")
            logger.error(f"Сообщение ошибки: {str(e)}")
            logger.error(f"Полный traceback:")
            for line in traceback.format_exception(type(e), e, e.__traceback__):
                logger.error(line.rstrip())
            
            # Проверяем признаки некритичных ошибок API
            is_api_error = any(pattern in error_msg for pattern in [
                'rate limit', 'quota', 'service unavailable', 
                'connection', 'timeout', 'network'
            ])
            
            if is_api_error:
                # Некритичная API ошибка - НЕ очищаем состояние
                # Экранируем фигурные скобки в сообщении об ошибке для безопасного логирования
                error_msg_safe = str(e).replace('{', '{{').replace('}', '}}')
                logger.error(f"⚠️ API ошибка для пользователя {user_id} ({error_type}): {error_msg_safe}")
                
                await safe_send_message(
                    bot=bot,
                    chat_id=chat_id,
                    text=f"⚠️ Временная проблема с API:\n\n{str(e)}\n\n"
                         f"Ваше состояние сохранено - попробуйте повторить через несколько минут."
                )
                
                raise ProcessingError(
                    f"API ошибка: {str(e)}",
                    "unknown",
                    "api_error"
                )
            else:
                # Неизвестная критичная ошибка - очищаем состояние
                # Экранируем фигурные скобки в сообщении об ошибке для безопасного логирования
                error_msg_safe = str(e).replace('{', '{{').replace('}', '}}')
                logger.error(f"❌ Неожиданная ошибка для пользователя {user_id} ({error_type}): {error_msg_safe}", exc_info=True)
                
                # Очищаем состояние при неизвестной ошибке
                await mapping_state_cache.clear_state(user_id)
                
                await safe_send_message(
                    bot=bot,
                    chat_id=chat_id,
                    text=f"❌ Произошла непредвиденная ошибка:\n\n{error_type}: {str(e)}\n\n"
                         f"Пожалуйста, начните обработку заново."
                )
                
                raise ProcessingError(
                    f"Неожиданная ошибка: {str(e)}",
                    "unknown",
                    "unexpected_error"
                )
    
    async def _suggest_template_if_needed(
        self,
        request: ProcessingRequest,
        transcription_result: Any,
        progress_tracker=None
    ) -> Optional[Any]:
        """
        Предложить умный выбор шаблона если template_id не задан
        
        Returns:
            Template или None если уже выбран
        """
        # Если шаблон уже выбран, возвращаем его
        if request.template_id:
            return await self.template_service.get_template_by_id(request.template_id)
        
        # Получаем все доступные шаблоны
        templates = await self.template_service.get_user_templates(request.user_id)
        
        if not templates:
            # Fallback на первый базовый шаблон
            all_templates = await self.template_service.get_all_templates()
            return all_templates[0] if all_templates else None
        
        # Классифицируем тип встречи для улучшения рекомендации
        from src.services.meeting_classifier import meeting_classifier
        meeting_type, type_scores = meeting_classifier.classify(
            transcription_result.transcription,
            diarization_analysis=None
        )
        logger.info(
            f"Тип встречи для рекомендации шаблона: {meeting_type} "
            f"(оценки: {', '.join(f'{k}={v:.2f}' for k, v in list(type_scores.items())[:3])})"
        )
        
        # Получаем историю использования с защитой от ошибок
        user_stats = await db.get_user_stats(request.user_id)
        template_history = []
        if user_stats and user_stats.get('favorite_templates'):
            # Безопасно извлекаем ID, пропуская записи без id
            template_history = [
                t['id'] for t in user_stats['favorite_templates'] 
                if isinstance(t, dict) and 'id' in t
            ]
        
        # ML-based рекомендация с учетом типа встречи
        suggestions = await smart_selector.suggest_templates(
            transcription=transcription_result.transcription,
            templates=templates,  # уже список объектов Template
            top_k=3,
            user_history=template_history,
            meeting_type=meeting_type,
            type_scores=type_scores,
            meeting_topic=request.meeting_topic
        )
        
        if suggestions:
            best_template, confidence = suggestions[0]
            logger.info(
                f"Рекомендован шаблон '{best_template.name}' "
                f"(уверенность: {confidence:.2%}, тип встречи: {meeting_type})"
            )
            
            # Возвращаем лучший вариант
            return best_template
        
        # Fallback - templates[0] уже объект Template
        return templates[0]
    
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
                                      request: ProcessingRequest, processing_metrics, meeting_type: str = None) -> Any:
        """Оптимизированная генерация LLM с кэшированием, двухэтапным подходом и валидацией"""
        
        # Создаем ключ кэша на основе транскрипции и шаблона
        transcription_hash = hash(str(transcription_result.transcription))
        template_hash = hash(str(template))
        participants_hash = (
            hash(json.dumps(
                sorted(request.participants_list, key=lambda x: x.get('name', '')),
                sort_keys=True
            )) if request.participants_list else "none"
        )
        cache_key = f"llm:{request.llm_provider}:{transcription_hash}:{template_hash}:{participants_hash}"
        
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
            
            # Определяем название используемой модели
            llm_model_name = self._get_model_display_name(request.llm_provider, openai_model_key)
            
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
            

            # Стандартная консолидированная генерация протокола
            if settings.enable_consolidated_two_request:
                logger.info("Использование новой консолидированной генерации протокола (2 запроса вместо 5-6)")

                from llm_providers import generate_protocol

                # Подготавливаем список участников
                participants_list = None
                if request.participants_list:
                    participants_list = "\n".join([
                        f"{p.get('name', '')} ({p.get('role', '')})".strip()
                        for p in request.participants_list
                        if p.get('name')
                    ])

                # Формируем метаданные встречи
                meeting_metadata = {
                    'meeting_topic': request.meeting_topic or '',
                    'meeting_date': request.meeting_date or '',
                    'meeting_time': request.meeting_time or '',
                    'participants': participants_list or ''
                }

                # Используем форматированную транскрипцию с метками SPEAKER_N если доступна диаризация
                # Это необходимо для корректного сопоставления спикеров в промпте извлечения
                transcription_text = transcription_result.transcription
                if hasattr(transcription_result, 'formatted_transcript') and transcription_result.formatted_transcript:
                    if transcription_result.diarization:
                        transcription_text = transcription_result.formatted_transcript
                        logger.info("Используется форматированная транскрипция с метками SPEAKER_N для диаризации")
                    else:
                        logger.info("Используется обычная транскрипция (диаризация недоступна)")
                else:
                    logger.info("Используется обычная транскрипция (formatted_transcript недоступен)")

                llm_result_data = await generate_protocol(
                    manager=llm_manager,
                    provider_name=request.llm_provider,
                    transcription=transcription_text,
                    template_variables=template_variables,
                    diarization_data=transcription_result.diarization,
                    diarization_analysis=diarization_analysis,
                    participants_list=participants_list,
                    meeting_metadata=meeting_metadata,
                    openai_model_key=openai_model_key,
                    speaker_mapping=request.speaker_mapping,
                    meeting_type=meeting_type,  # Передаем тип встречи из первого запроса
                    meeting_topic=request.meeting_topic,
                    meeting_date=request.meeting_date,
                    meeting_time=request.meeting_time,
                    participants=request.participants_list,
                    # Add protocol context parameters
                    meeting_agenda=request.meeting_agenda,
                    project_list=request.project_list
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
                    openai_model_key,
                    request.speaker_mapping,
                    request.meeting_topic,
                    request.meeting_date,
                    request.meeting_time,
                    request.participants_list,
                    request.meeting_agenda,
                    request.project_list
                )
                
                if not llm_result.success:
                    # Безопасный доступ к атрибуту error
                    error_msg = getattr(llm_result, 'error', None)
                    if error_msg is None:
                        error_msg = "Неизвестная ошибка LLM"
                    elif isinstance(error_msg, Exception):
                        error_msg = str(error_msg)
                    raise ProcessingError(f"Ошибка LLM: {error_msg}", 
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
            
            # Логирование сводки по кешированию токенов
            if (settings.log_cache_metrics and 
                hasattr(processing_metrics, 'total_cached_tokens') and 
                hasattr(processing_metrics, 'get_cache_summary') and
                processing_metrics.total_cached_tokens > 0):
                cache_summary = processing_metrics.get_cache_summary()
                logger.info("=" * 60)
                logger.info("📊 Итоговая сводка по кешированию токенов:")
                logger.info(f"   Prompt токенов: {cache_summary['total_prompt_tokens']:,}")
                logger.info(f"   Кешировано: {cache_summary['total_cached_tokens']:,} ({cache_summary['cache_hit_rate_percent']}%)")
                if cache_summary['cost_saved'] > 0:
                    logger.info(f"   💰 Экономия: ${cache_summary['cost_saved']:.4f} ({cache_summary['savings_percent']:.1f}%)")
                    logger.info(f"   Стоимость: ${cache_summary['cost_with_cache']:.4f} (без кеша: ${cache_summary['cost_without_cache']:.4f})")
                logger.info("=" * 60)
        
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

            # Создаем словарь переменных с начальными значениями
            template_variables = {}

            # Базовые переменные, которые всегда должны быть доступны (метаданные)
            core_variables = {
                'meeting_title': '',
                'meeting_date': '',
                'meeting_time': '',
                'participants': ''
            }
            
            # Инициализируем базовыми переменными
            template_variables.update(core_variables)

            # Добавляем переменные из шаблона
            for var in variables_list:
                template_variables[var] = ""  # Пустое значение для заполнения LLM

            logger.info(f"Подготовлены переменные шаблона: {list(template_variables.keys())}")
            return template_variables

        except Exception as e:
            logger.error(f"Ошибка при извлечении переменных из шаблона: {e}")
            # Возвращаем расширенный набор переменных как fallback
            return {
                'meeting_title': '',
                'meeting_date': '',
                'meeting_time': '',
                'participants': '',
                'agenda': '',
                'discussion': '',
                'key_points': '',
                'decisions': '',
                'action_items': '',
                'tasks': '',
                'next_steps': '',
                'deadlines': '',
                'issues': '',
                'questions': '',
                'risks_and_blockers': '',
                'technical_issues': '',
                'architecture_decisions': '',
                'technical_tasks': '',
                'speaker_contributions': '',
                'dialogue_analysis': '',
                'speakers_summary': '',
                'next_meeting': '',
                'additional_notes': '',
                'date': '',
                'time': '',
                'managers': '',
                'platform': '',
                'learning_objectives': '',
                'key_concepts': '',
                'examples_and_cases': '',
                'practical_exercises': '',
                'homework': '',
                'materials': '',
                'next_sprint_plans': ''
            }

    def _get_model_display_name(self, provider: str, openai_model_key: Optional[str] = None) -> str:
        """Получить читаемое название модели"""
        if provider == "openai":
            if openai_model_key:
                # Ищем пресет модели
                try:
                    preset = next((p for p in settings.openai_models if p.key == openai_model_key), None)
                    if preset:
                        return preset.name  # Используем читаемое имя из пресета
                except Exception:
                    pass
            # Fallback на модель по умолчанию
            return settings.openai_model or "GPT-4o"
        
        # Для других провайдеров - заглавная буква
        return provider.capitalize()

    async def _generate_llm_response(self, transcription_result, template,
                                   template_variables, llm_provider, openai_model_key=None, speaker_mapping=None,
                                   meeting_topic=None, meeting_date=None, meeting_time=None, participants=None,
                                   meeting_agenda=None, project_list=None):
        """Генерация ответа LLM с постобработкой"""
        llm_result = await self.llm_service.generate_protocol_with_fallback(
            llm_provider, transcription_result.transcription, template_variables,
            transcription_result.diarization if hasattr(transcription_result, 'diarization') else None,
            openai_model_key=openai_model_key,
            speaker_mapping=speaker_mapping,
            meeting_topic=meeting_topic,
            meeting_date=meeting_date,
            meeting_time=meeting_time,
            participants=participants,
            meeting_agenda=meeting_agenda,
            project_list=project_list
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
    
    async def _download_telegram_file(self, request: ProcessingRequest) -> str:
        """Скачать Telegram файл и вернуть путь
        
        Args:
            request: Запрос на обработку с file_id
            
        Returns:
            Путь к скачанному файлу
            
        Raises:
            ProcessingError: Если файл не удалось скачать
        """
        file_url = await self.file_service.get_telegram_file_url(request.file_id)
        temp_file_path = f"temp/{request.file_name}"
        
        # Используем OptimizedHTTPClient для скачивания
        async with OptimizedHTTPClient() as http_client:
            result = await http_client.download_file(file_url, temp_file_path)
            
            if not result["success"]:
                error_msg = result.get('error', 'Неизвестная ошибка скачивания')
                raise ProcessingError(
                    f"Ошибка скачивания: {error_msg}", 
                    request.file_name, 
                    "download"
                )
        
        logger.info(f"Файл скачан: {temp_file_path} ({result['bytes_downloaded']} байт)")
        return temp_file_path
    
    async def _cleanup_temp_file(self, file_path: str):
        """Асинхронная очистка временного файла"""
        try:
            await asyncio.sleep(1)  # Небольшая задержка
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.debug(f"Удален временный файл: {file_path}")
        except Exception as e:
            logger.warning(f"Не удалось удалить временный файл {file_path}: {e}")
    
    def _generate_result_cache_key(self, request: ProcessingRequest, file_hash: str) -> str:
        """Генерировать ключ кэша для полного результата
        
        Args:
            request: Запрос на обработку
            file_hash: SHA-256 хеш содержимого файла
            
        Returns:
            Ключ кэша
        """
        key_data = {
            "file_hash": file_hash,  # Используем хеш содержимого вместо file_id
            "template_id": request.template_id,
            "llm_provider": request.llm_provider,
            "language": request.language,
            "participants_list": request.participants_list,
            "meeting_topic": request.meeting_topic,
            "meeting_date": request.meeting_date,
            "meeting_time": request.meeting_time,
            "speaker_mapping": request.speaker_mapping
        }
        return performance_cache._generate_key("full_result", key_data)
    
    def _format_protocol(self, template: Any, llm_result: Any,
                        transcription_result: Any) -> str:
        """Форматирование протокола с мягкой обработкой типов результата LLM"""
        from jinja2 import Template as Jinja2Template
        from jinja2 import meta

        # Если LLM вернул строку — считаем это готовым текстом протокола
        if isinstance(llm_result, str):
            text = llm_result.strip()
            if text:
                logger.info(f"LLM вернул готовый текст протокола (длина: {len(text)})")
                return text
            # Пустая строка — падаем на простой формат
            logger.warning("LLM вернул пустую строку, используем fallback")
            return f"# Протокол\n\n{transcription_result.transcription}"

        # Получаем содержимое шаблона
        if hasattr(template, 'content'):
            template_content = template.content
        elif isinstance(template, dict):
            template_content = template.get('content', '')
        else:
            template_content = str(template)

        # Если есть маппинг — используем Jinja2 для подстановки
        if isinstance(llm_result, dict):
            logger.info(f"[DEBUG] Форматирование протокола с шаблоном")
            logger.info(f"[DEBUG] Тип шаблона: {type(template)}")
            logger.info(f"[DEBUG] Длина содержимого шаблона: {len(template_content)}")
            logger.info(f"[DEBUG] Тип LLM результата: {type(llm_result)}")
            logger.info(f"[DEBUG] Ключи в LLM результате: {list(llm_result.keys())[:10]}...")  # Первые 10 ключей

            # Извлекаем переменные из шаблона
            try:
                jinja_template = Jinja2Template(template_content)
                template_variables = meta.find_undeclared_variables(jinja_template.environment.parse(template_content))
                logger.info(f"[DEBUG] Переменные в шаблоне: {sorted(list(template_variables))}")

                # Проверяем, какие переменные есть в LLM результате
                available_variables = set(llm_result.keys())
                missing_variables = template_variables - available_variables
                found_variables = template_variables & available_variables

                logger.info(f"[DEBUG] Найденные переменные: {sorted(list(found_variables))}")
                logger.info(f"[DEBUG] Отсутствующие переменные: {sorted(list(missing_variables))}")

                # Анализ совместимости шаблона и LLM данных
                if template_variables:
                    compatibility_score = len(found_variables) / len(template_variables)
                    logger.info(f"[DEBUG] Совместимость шаблона: {compatibility_score:.1%} ({len(found_variables)}/{len(template_variables)} переменных)")

                    # Проверяем на низкую совместимость
                    if compatibility_score < 0.4:
                        logger.warning(f"⚠️ Низкая совместимость шаблона ({compatibility_score:.1%}) - рекомендуется другой шаблон")

                        # Предлагаем переменные, которые есть в LLM но не в шаблоне
                        llm_only_variables = available_variables - template_variables
                        if llm_only_variables:
                            important_llm_vars = [var for var in llm_only_variables if var in [
                                'agenda', 'key_points', 'decisions', 'action_items', 'discussion', 'meeting_title'
                            ]]
                            if important_llm_vars:
                                logger.warning(f"🔥 Важные поля LLM отсутствуют в шаблоне: {important_llm_vars}")

                    # Проверяем на высокую совместимость
                    elif compatibility_score >= 0.7:
                        logger.info(f"✅ Хорошая совместимость шаблона ({compatibility_score:.1%})")

                # Добавляем пустые значения для отсутствующих переменных
                if missing_variables:
                    logger.warning(f"Добавляю пустые значения для отсутствующих переменных: {missing_variables}")
                    for var in missing_variables:
                        llm_result[var] = ''

                # Проверяем наличие важных полей
                important_fields = ['meeting_title', 'participants', 'discussion', 'decisions']
                missing_important = [field for field in important_fields if not llm_result.get(field, '').strip()]
                if missing_important:
                    logger.warning(f"Отсутствуют важные поля: {missing_important}")
                else:
                    logger.info("Все важные поля присутствуют и не пусты")

                # Пробуем отрендерить шаблон
                try:
                    rendered_result = jinja_template.render(**llm_result)
                    result_length = len(rendered_result.strip())
                    logger.info(f"[DEBUG] Шаблон успешно отрендерен. Длина результата: {result_length}")

                    # Проверяем, что результат не пустой или не содержит только разметку
                    if result_length > 50:  # Минимальная длина для содержательного протокола
                        return rendered_result
                    else:
                        logger.warning(f"Результат рендеринга слишком короткий ({result_length} символов), используем fallback")

                except Exception as render_error:
                    logger.error(f"Ошибка при рендеринге шаблона: {render_error}")
                    logger.error(f"Тип ошибки: {type(render_error)}")
                    logger.error(f"Детали ошибки: {str(render_error)}")

            except Exception as template_error:
                logger.error(f"Ошибка при анализе шаблона: {template_error}")
                logger.error(f"Тип ошибки: {type(template_error)}")

        # Enhanced Fallback: используем данные из LLM результата для создания структурированного протокола
        if isinstance(llm_result, dict):
            logger.warning("Используем enhanced fallback с данными LLM")

            # Определяем приоритет полей и их заголовки
            field_priority = [
                ('meeting_title', 'Протокол встречи'),
                ('meeting_date', None), ('meeting_time', None),  # Обрабатываем отдельно
                ('participants', 'Участники'),
                ('agenda', 'Повестка дня'),
                ('discussion', 'Ход обсуждения'),
                ('key_points', 'Ключевые моменты и выводы'),
                ('decisions', 'Принятые решения'),
                ('action_items', 'Поручения и ответственные'),
                ('tasks', 'Распределение задач'),
                ('next_steps', 'Следующие шаги'),
                ('deadlines', 'Сроки выполнения'),
                ('risks_and_blockers', 'Риски и блокеры'),
                ('issues', 'Выявленные проблемы'),
                ('questions', 'Открытые вопросы'),
                ('next_meeting', 'Следующая встреча'),
                ('additional_notes', 'Дополнительные заметки'),
                # Технические поля
                ('technical_issues', 'Технические вопросы'),
                ('architecture_decisions', 'Архитектурные решения'),
                ('technical_tasks', 'Технические задачи'),
                # Образовательные поля
                ('learning_objectives', 'Цели обучения'),
                ('key_concepts', 'Ключевые концепции'),
                ('examples_and_cases', 'Примеры и кейсы'),
                # Agile поля
                ('next_sprint_plans', 'Планы на следующий спринт')
            ]

            # Собираем протокол из доступных полей в порядке приоритета
            protocol_parts = []
            used_sections = []

            # Заголовок
            title = llm_result.get('meeting_title', 'Протокол встречи').strip()
            protocol_parts.append(f"# {title}")

            # Дата и время (если есть)
            date = llm_result.get('meeting_date', llm_result.get('date', '')).strip()
            time = llm_result.get('meeting_time', llm_result.get('time', '')).strip()

            if date or time:
                datetime_parts = []
                if date:
                    datetime_parts.append(f"**Дата:** {date}")
                if time:
                    datetime_parts.append(f"**Время:** {time}")
                if datetime_parts:
                    protocol_parts.append(" | ".join(datetime_parts))

            # Участники (если есть)
            participants = llm_result.get('participants', '').strip()
            if participants:
                protocol_parts.append(f"**Участники:**\n{participants}")

            # Добавляем секции в порядке приоритета, только если есть содержимое
            for field, section_name in field_priority[4:]:  # Пропускаем уже обработанные поля
                content = llm_result.get(field, '').strip()
                if content and section_name:
                    protocol_parts.append(f"\n## {section_name}\n{content}")
                    used_sections.append(field)

            # Добавляем информацию о том, какие поля были использованы
            total_fields = len([f for f, _ in field_priority if llm_result.get(f, '').strip()])
            logger.info(f"Enhanced fallback использован {total_fields} полей: {used_sections}")

            fallback_result = '\n\n'.join(protocol_parts)
            result_length = len(fallback_result)
            logger.info(f"Enhanced fallback создан. Длина: {result_length} символов")

            # Проверяем, что результат достаточно содержательный
            if result_length > 200:
                return fallback_result
            else:
                logger.warning(f"Enhanced fallback результат слишком короткий ({result_length}), используем базовый fallback")

        # Последний fallback: базовый текст транскрипции
        logger.error("Используем последний fallback - базовую транскрипцию")
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
class ServiceFactory:
    """Фабрика для создания оптимизированных сервисов"""
    
    @staticmethod
    def create_processing_service() -> ProcessingService:
        """Создать оптимизированный сервис обработки"""
        return ProcessingService()
    
    @staticmethod
    async def create_with_prewarming() -> ProcessingService:
        """Создать сервис с предварительным прогревом"""
        service = ProcessingService()
        
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
