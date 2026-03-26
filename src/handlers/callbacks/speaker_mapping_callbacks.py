"""
Обработчики callback запросов для сопоставления спикеров с участниками.
"""

from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from loguru import logger

from services import UserService, TemplateService, EnhancedLLMService, ProcessingService
from src.utils.telegram_safe import safe_edit_text
from .helpers import _safe_callback_answer


def setup_speaker_mapping_callbacks(user_service: UserService, template_service: TemplateService,
                                     llm_service: EnhancedLLMService, processing_service: ProcessingService) -> Router:
    """Настройка обработчиков callback запросов для сопоставления спикеров"""
    router = Router()

    @router.callback_query(F.data.startswith("sm_change:"))
    async def speaker_mapping_change_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик начала изменения сопоставления спикера"""
        try:
            await _safe_callback_answer(callback)

            # Парсим данные: sm_change:{speaker_id}:{user_id}
            parts = callback.data.split(":")
            if len(parts) < 3:
                logger.error(f"Неверный формат callback data: {callback.data}")
                await callback.answer("❌ Ошибка формата запроса")
                return

            speaker_id = parts[1]
            user_id_from_callback = int(parts[2])

            # Проверяем владельца
            if callback.from_user.id != user_id_from_callback:
                await callback.answer("❌ Это не ваш запрос")
                return

            # Загружаем состояние
            from src.services.mapping_state_cache import mapping_state_cache
            state_data = await mapping_state_cache.load_state(user_id_from_callback)

            if not state_data:
                await safe_edit_text(
                    callback.message,
                    "❌ Состояние обработки не найдено или истекло.\n\n"
                    "Пожалуйста, начните обработку заново."
                )
                await callback.answer()
                return

            speaker_mapping = state_data.get('speaker_mapping', {})
            diarization_data = state_data.get('diarization_data', {})
            participants = state_data.get('participants_list', [])

            # Извлекаем speakers_text из кеша если доступен
            transcription_result = state_data.get('transcription_result', {})
            speakers_text = transcription_result.get('speakers_text') if transcription_result else None

            # Обновляем сообщение, показывая выбор участников для этого спикера
            from src.ux.speaker_mapping_ui import update_mapping_message
            await update_mapping_message(
                callback.message,
                speaker_mapping,
                diarization_data,
                participants,
                user_id_from_callback,
                current_editing_speaker=speaker_id,
                speakers_text=speakers_text
            )

            await callback.answer()

        except Exception as e:
            logger.error(f"Ошибка в speaker_mapping_change_callback: {e}", exc_info=True)
            await _safe_callback_answer(callback, "❌ Произошла ошибка")

    @router.callback_query(F.data.startswith("sm_select:"))
    async def speaker_mapping_select_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик выбора участника для спикера"""
        try:
            await _safe_callback_answer(callback)

            # Парсим данные: sm_select:{speaker_id}:{participant_idx}:{user_id}
            parts = callback.data.split(":")
            if len(parts) < 4:
                logger.error(f"Неверный формат callback data: {callback.data}")
                await callback.answer("❌ Ошибка формата запроса")
                return

            speaker_id = parts[1]
            participant_idx_str = parts[2]
            user_id_from_callback = int(parts[3])

            # Проверяем владельца
            if callback.from_user.id != user_id_from_callback:
                await callback.answer("❌ Это не ваш запрос")
                return

            # Загружаем состояние
            from src.services.mapping_state_cache import mapping_state_cache
            state_data = await mapping_state_cache.load_state(user_id_from_callback)

            if not state_data:
                await safe_edit_text(
                    callback.message,
                    "❌ Состояние обработки не найдено или истекло.\n\n"
                    "Пожалуйста, начните обработку заново."
                )
                await callback.answer()
                return

            speaker_mapping = state_data.get('speaker_mapping', {}).copy()
            diarization_data = state_data.get('diarization_data', {})
            participants = state_data.get('participants_list', [])

            # Обрабатываем выбор
            if participant_idx_str == "none":
                # Удаляем сопоставление
                speaker_mapping.pop(speaker_id, None)
                await callback.answer("✅ Сопоставление удалено")
            else:
                try:
                    participant_idx = int(participant_idx_str)
                    if 0 <= participant_idx < len(participants):
                        participant_name = participants[participant_idx].get('name', '')
                        if participant_name:
                            # Проверяем, не используется ли уже этот участник другим спикером
                            used_by = None
                            for sid, pname in speaker_mapping.items():
                                if sid != speaker_id and pname == participant_name:
                                    used_by = sid
                                    break

                            if used_by:
                                await callback.answer(
                                    f"⚠️ Этот участник уже сопоставлен с {used_by}",
                                    show_alert=True
                                )
                                return

                            speaker_mapping[speaker_id] = participant_name
                            await callback.answer("✅ Сопоставление изменено")
                        else:
                            await callback.answer("❌ Имя участника не найдено")
                            return
                    else:
                        await callback.answer("❌ Неверный индекс участника")
                        return
                except ValueError:
                    await callback.answer("❌ Неверный формат индекса")
                    return

            # Обновляем состояние в кеше
            await mapping_state_cache.update_mapping(user_id_from_callback, speaker_mapping)

            # Извлекаем speakers_text из кеша если доступен
            transcription_result = state_data.get('transcription_result', {})
            speakers_text = transcription_result.get('speakers_text') if transcription_result else None

            # Обновляем сообщение (возвращаемся к основному виду)
            from src.ux.speaker_mapping_ui import update_mapping_message
            await update_mapping_message(
                callback.message,
                speaker_mapping,
                diarization_data,
                participants,
                user_id_from_callback,
                current_editing_speaker=None,
                speakers_text=speakers_text
            )

        except Exception as e:
            logger.error(f"Ошибка в speaker_mapping_select_callback: {e}", exc_info=True)
            await _safe_callback_answer(callback, "❌ Произошла ошибка")

    @router.callback_query(F.data.startswith("sm_cancel:"))
    async def speaker_mapping_cancel_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик отмены редактирования (возврат к основному виду)"""
        try:
            await _safe_callback_answer(callback)

            # Парсим данные: sm_cancel:{user_id}
            parts = callback.data.split(":")
            if len(parts) < 2:
                logger.error(f"Неверный формат callback data: {callback.data}")
                await callback.answer("❌ Ошибка формата запроса")
                return

            user_id_from_callback = int(parts[1])

            # Проверяем владельца
            if callback.from_user.id != user_id_from_callback:
                await callback.answer("❌ Это не ваш запрос")
                return

            # Загружаем состояние
            from src.services.mapping_state_cache import mapping_state_cache
            state_data = await mapping_state_cache.load_state(user_id_from_callback)

            if not state_data:
                await safe_edit_text(
                    callback.message,
                    "❌ Состояние обработки не найдено или истекло.\n\n"
                    "Пожалуйста, начните обработку заново."
                )
                await callback.answer()
                return

            speaker_mapping = state_data.get('speaker_mapping', {})
            diarization_data = state_data.get('diarization_data', {})
            participants = state_data.get('participants_list', [])

            # Извлекаем speakers_text из кеша если доступен
            transcription_result = state_data.get('transcription_result', {})
            speakers_text = transcription_result.get('speakers_text') if transcription_result else None

            # Возвращаемся к основному виду
            from src.ux.speaker_mapping_ui import update_mapping_message
            await update_mapping_message(
                callback.message,
                speaker_mapping,
                diarization_data,
                participants,
                user_id_from_callback,
                current_editing_speaker=None,
                speakers_text=speakers_text
            )

            await callback.answer()

        except Exception as e:
            logger.error(f"Ошибка в speaker_mapping_cancel_callback: {e}", exc_info=True)
            await _safe_callback_answer(callback, "❌ Произошла ошибка")

    @router.callback_query(F.data.startswith("sm_confirm:"))
    async def speaker_mapping_confirm_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик подтверждения сопоставления и продолжения обработки"""
        try:
            await _safe_callback_answer(callback, "⏳ Продолжаю обработку...")

            # Парсим данные: sm_confirm:{user_id}
            parts = callback.data.split(":")
            if len(parts) < 2:
                logger.error(f"Неверный формат callback data: {callback.data}")
                await callback.answer("❌ Ошибка формата запроса")
                return

            user_id_from_callback = int(parts[1])

            # Проверяем владельца
            if callback.from_user.id != user_id_from_callback:
                await callback.answer("❌ Это не ваш запрос")
                return

            # Загружаем состояние
            from src.services.mapping_state_cache import mapping_state_cache
            state_data = await mapping_state_cache.load_state(user_id_from_callback)

            if not state_data:
                await safe_edit_text(
                    callback.message,
                    "❌ Состояние обработки не найдено или истекло.\n\n"
                    "Пожалуйста, начните обработку заново."
                )
                return

            speaker_mapping = state_data.get('speaker_mapping', {})

            # Обновляем сообщение (кратко, без обещаний - реальная обработка начнется в следующем сообщении)
            await safe_edit_text(
                callback.message,
                "✅ **Сопоставление подтверждено**",
                parse_mode="Markdown"
            )

            # Очищаем состояние FSM
            await state.clear()

            # Продолжаем обработку
            await processing_service.continue_processing_after_mapping_confirmation(
                user_id=user_id_from_callback,
                confirmed_mapping=speaker_mapping,
                bot=callback.bot,
                chat_id=callback.message.chat.id
            )

            # Очищаем кеш состояния
            await mapping_state_cache.clear_state(user_id_from_callback)

        except Exception as e:
            # Расширенное логирование ошибки
            import traceback
            import sys

            logger.error(f"❌ Ошибка в speaker_mapping_confirm_callback")
            logger.error(f"Тип ошибки: {type(e).__name__}")
            # Экранируем фигурные скобки в сообщении об ошибке для безопасного логирования
            error_msg_safe = str(e).replace('{', '{{').replace('}', '}}')
            logger.error(f"Детали: {error_msg_safe}")

            # Логируем контекст callback
            try:
                if 'user_id_from_callback' in locals():
                    logger.error(f"Контекст callback:")
                    logger.error(f"  - User ID: {user_id_from_callback}")
                    logger.error(f"  - Chat ID: {callback.message.chat.id}")
                    logger.error(f"  - Callback data: {callback.data}")

                    # Пытаемся загрузить состояние для дополнительного контекста
                    try:
                        from src.services.mapping_state_cache import mapping_state_cache
                        state_data = await mapping_state_cache.load_state(user_id_from_callback)
                        if state_data:
                            request_data = state_data.get('request_data', {})
                            logger.error(f"  - LLM провайдер: {request_data.get('llm_provider', 'unknown')}")
                            logger.error(f"  - Файл: {request_data.get('file_name', 'unknown')}")
                    except Exception as state_error:
                        logger.warning(f"Не удалось получить дополнительный контекст: {state_error}")
            except Exception as log_error:
                logger.warning(f"Ошибка при логировании контекста: {log_error}")

            # Полный traceback - используем несколько методов для гарантированного вывода
            logger.error("Полный traceback:", exc_info=True)

            # Дополнительно выводим traceback как строку для надёжности
            tb_lines = traceback.format_exception(type(e), e, e.__traceback__)
            logger.error("Детальный traceback (построчно):")
            for line in tb_lines:
                logger.error(line.rstrip())

            # Выводим стек вызовов
            logger.error(f"Стек вызовов: {traceback.format_stack()}")

            await safe_edit_text(
                callback.message,
                "❌ Произошла ошибка при продолжении обработки.\n\n"
                "Пожалуйста, попробуйте начать обработку заново."
            )

    @router.callback_query(F.data.startswith("sm_skip:"))
    async def speaker_mapping_skip_callback(callback: CallbackQuery, state: FSMContext):
        """Обработчик пропуска сопоставления (продолжение без имен)"""
        try:
            await _safe_callback_answer(callback, "⏳ Продолжаю обработку без сопоставления...")

            # Парсим данные: sm_skip:{user_id}
            parts = callback.data.split(":")
            if len(parts) < 2:
                logger.error(f"Неверный формат callback data: {callback.data}")
                await callback.answer("❌ Ошибка формата запроса")
                return

            user_id_from_callback = int(parts[1])

            # Проверяем владельца
            if callback.from_user.id != user_id_from_callback:
                await callback.answer("❌ Это не ваш запрос")
                return

            # Загружаем состояние
            from src.services.mapping_state_cache import mapping_state_cache
            state_data = await mapping_state_cache.load_state(user_id_from_callback)

            if not state_data:
                await safe_edit_text(
                    callback.message,
                    "❌ Состояние обработки не найдено или истекло.\n\n"
                    "Пожалуйста, начните обработку заново."
                )
                return

            # Продолжаем с пустым mapping
            empty_mapping = {}

            # Обновляем сообщение
            await safe_edit_text(
                callback.message,
                "⏭️ **Сопоставление пропущено**\n\n"
                "⏳ Продолжаю генерацию протокола без замены имен спикеров...",
                parse_mode="Markdown"
            )

            # Очищаем состояние FSM
            await state.clear()

            # Продолжаем обработку с пустым mapping
            await processing_service.continue_processing_after_mapping_confirmation(
                user_id=user_id_from_callback,
                confirmed_mapping=empty_mapping,
                bot=callback.bot,
                chat_id=callback.message.chat.id
            )

            # Очищаем кеш состояния
            await mapping_state_cache.clear_state(user_id_from_callback)

        except Exception as e:
            logger.error(f"Ошибка в speaker_mapping_skip_callback: {e}", exc_info=True)
            await safe_edit_text(
                callback.message,
                "❌ Произошла ошибка при продолжении обработки.\n\n"
                "Пожалуйста, попробуйте начать обработку заново."
            )

    return router
