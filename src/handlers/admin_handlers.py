"""
Обработчики административных команд
"""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from loguru import logger

from src.api.monitoring import monitoring_api
from src.config import settings
from src.handlers.admin_model_handlers import setup_admin_model_handlers
from src.reliability.health_check import health_checker
from src.services.processing_service import ProcessingService
from src.utils.admin_utils import is_admin
from src.utils.telegram_safe import safe_answer, safe_edit_text
from src.ux import admin_views
from src.ux.admin_views import ACCESS_DENIED
from src.ux.html_text import esc

# Отказ статистики размножился по пяти хендлерам (критика v10). Текст
# исключения пользователю не показываем — он уже в логе.
_STATS_FAILED = (
    "❌ Не удалось собрать статистику.\n"
    "Попробуйте ещё раз через минуту."
)


# Импорт сервиса очистки
try:
    from src.services.cleanup_service import cleanup_service
    CLEANUP_SERVICE_AVAILABLE = True
except ImportError:
    CLEANUP_SERVICE_AVAILABLE = False


def setup_admin_handlers(processing_service: ProcessingService) -> Router:
    """Настройка административных обработчиков"""
    router = Router()

    @router.message(Command("status", "st"))
    async def status_handler(message: Message):
        """Обработчик команды /status - статус системы"""
        if not is_admin(message.from_user.id):
            await message.answer(ACCESS_DENIED)
            return
        
        try:
            report = monitoring_api.format_status_report()
            await safe_answer(message, report, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка в status_handler: {e}")
            await message.answer(f"❌ Ошибка при получении статуса: {e}")
    
    @router.message(Command("health"))
    async def health_handler(message: Message):
        """Обработчик команды /health - детальная проверка здоровья"""
        if not is_admin(message.from_user.id):
            await message.answer(ACCESS_DENIED)
            return
        
        try:
            # Запускаем проверку здоровья
            await message.answer("⏳ Проверяю здоровье системы")

            health_results = await health_checker.check_all()
            report = admin_views.health_report(health_results)
            await safe_answer(message, report, parse_mode="HTML")

        except Exception as e:
            logger.error(f"Ошибка в health_handler: {e}")
            await message.answer(f"❌ Ошибка при проверке здоровья: {e}")
    
    @router.message(Command("stats"))
    async def stats_handler(message: Message):
        """Обработчик команды /stats - детальная статистика"""
        if not is_admin(message.from_user.id):
            await message.answer(ACCESS_DENIED)
            return
        
        try:
            stats = monitoring_api.get_system_stats()

            # Форматируем статистику
            report_lines = ["<b>Детальная статистика системы</b>\n"]

            # Производительность
            perf = stats.get("performance", {})
            if perf and "error" not in perf:
                report_lines.extend([
                    "<b>Производительность</b>",
                    f"• Всего запросов: {perf.get('total_requests', 0)}",
                    f"• Успешных: {perf.get('total_requests', 0) - perf.get('total_errors', 0)}",
                    f"• Ошибок: {perf.get('total_errors', 0)} ({perf.get('error_rate', 0):.1f}%)",
                    f"• Среднее время: {perf.get('average_processing_time', 0):.3f}с",
                    f"• Максимальное время: {perf.get('max_processing_time', 0):.3f}с",
                    f"• Минимальное время: {perf.get('min_processing_time', 0):.3f}с",
                    f"• Активных пользователей: {perf.get('active_users', 0)}",
                    ""
                ])

            # Rate limiting
            rate_limits = stats.get("rate_limits", {})
            if rate_limits and "error" not in rate_limits:
                total_requests = sum(
                    limiter.get("total_requests", 0)
                    for limiter in rate_limits.values()
                    if isinstance(limiter, dict)
                )
                total_blocked = sum(
                    limiter.get("blocked_requests", 0)
                    for limiter in rate_limits.values()
                    if isinstance(limiter, dict)
                )

                report_lines.extend([
                    "<b>Rate Limiting</b>",
                    f"• Всего запросов: {total_requests}",
                    f"• Заблокировано: {total_blocked}",
                    f"• Процент блокировки: {(total_blocked/max(1, total_requests))*100:.1f}%",
                    ""
                ])

            # Компоненты
            health = stats.get("health", {})
            components = health.get("components", {})
            if components:
                report_lines.append("<b>Статистика компонентов</b>")
                for name, comp in components.items():
                    status = comp.get("status", "unknown")
                    checks = comp.get("total_checks", 0)
                    failures = comp.get("total_failures", 0)
                    failure_rate = comp.get("failure_rate", 0)

                    report_lines.append(f"• <b>{esc(name)}</b>: {esc(status)}")
                    report_lines.append(f"  Проверок: {checks}, неудач: {failures} ({failure_rate:.1f}%)")

                report_lines.append("")

            report = "\n".join(report_lines)
            await safe_answer(message, report, parse_mode="HTML")

        except Exception as e:
            logger.error(f"Ошибка в stats_handler: {e}")
            await message.answer(_STATS_FAILED)
    
    @router.message(Command("reset_reliability"))
    async def reset_reliability_handler(message: Message):
        """Обработчик команды /reset_reliability - сброс компонентов надежности"""
        if not is_admin(message.from_user.id):
            await message.answer(ACCESS_DENIED)
            return
        
        try:
            await message.answer("⏳ Сбрасываю компоненты надежности")

            # Сбрасываем компоненты
            from src.llm import protocol_generator
            await protocol_generator.reset()
            await processing_service.reset_reliability_components()

            # Сбрасываем health checker
            for name, cb in health_checker.component_health.items():
                cb.consecutive_failures = 0
                cb.status = health_checker.HealthStatus.UNKNOWN

            await message.answer("✅ Компоненты надежности сброшены успешно.")
            
        except Exception as e:
            logger.error(f"Ошибка в reset_reliability_handler: {e}")
            await message.answer(f"❌ Ошибка при сбросе: {e}")
    
    @router.message(Command("export_stats"))
    async def export_stats_handler(message: Message):
        """Обработчик команды /export_stats - экспорт статистики в JSON"""
        if not is_admin(message.from_user.id):
            await message.answer(ACCESS_DENIED)
            return
        
        try:
            # Экспортируем статистику
            json_stats = monitoring_api.export_stats_json()
            
            # Сохраняем во временный файл
            import os
            import tempfile
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
                f.write(json_stats)
                temp_path = f.name
            
            try:
                # Отправляем файл
                from aiogram.types import FSInputFile
                
                file_input = FSInputFile(temp_path, filename="bot_stats.json")
                await message.answer_document(
                    file_input,
                    caption="Экспорт статистики системы"
                )
                
            finally:
                # Удаляем временный файл
                try:
                    os.unlink(temp_path)
                except:
                    pass
            
        except Exception as e:
            logger.error(f"Ошибка в export_stats_handler: {e}")
            await message.answer(f"❌ Ошибка при экспорте: {e}")
    
    @router.message(Command("transcription_mode"))
    async def transcription_mode_handler(message: Message):
        """Обработчик команды /transcription_mode - переключение режима транскрипции"""
        if not is_admin(message.from_user.id):
            await message.answer(ACCESS_DENIED)
            return
        
        try:
            text, keyboard = admin_views.transcription_mode_view(settings.transcription_mode)
            await safe_answer(message, text, reply_markup=keyboard, parse_mode="HTML")

        except Exception as e:
            logger.error(f"Ошибка в transcription_mode_handler: {e}")
            await message.answer(f"❌ Ошибка при получении режимов транскрипции: {e}")
    
    @router.message(Command("admin_help"))
    async def admin_help_handler(message: Message):
        """Обработчик команды /admin_help - справка по административным командам"""
        if not is_admin(message.from_user.id):
            await message.answer(ACCESS_DENIED)
            return
        
        await safe_answer(message, admin_views.admin_help_text(), parse_mode="HTML")

    @router.message(Command("performance"))
    async def performance_handler(message: Message):
        """Обработчик команды /performance - статистика производительности"""
        if not is_admin(message.from_user.id):
            await message.answer(ACCESS_DENIED)
            return
        
        try:
            from src.performance import memory_optimizer, metrics_collector, performance_cache, task_pool
            
            # Собираем статистику
            cache_stats = performance_cache.get_stats()
            memory_stats = memory_optimizer.get_optimization_stats()
            task_stats = task_pool.get_stats()
            metrics_stats = metrics_collector.get_current_stats()

            report = admin_views.performance_report(
                cache_stats, memory_stats, task_stats, metrics_stats
            )
            await safe_answer(message, report, parse_mode="HTML")

        except Exception as e:
            logger.error(f"Ошибка в performance_handler: {e}")
            await message.answer(_STATS_FAILED)
    
    @router.message(Command("optimize"))
    async def optimize_handler(message: Message):
        """Обработчик команды /optimize - принудительная оптимизация"""
        if not is_admin(message.from_user.id):
            await message.answer(ACCESS_DENIED)
            return
        
        try:
            from src.performance import memory_optimizer, performance_cache
            
            status_msg = await message.answer("⏳ Выполняю оптимизацию")

            # Оптимизация памяти
            memory_result = await memory_optimizer.optimize_memory()

            # Очистка кэша
            await performance_cache.cleanup_expired()

            # Отчет об оптимизации
            report = (
                "✅ <b>Оптимизация завершена</b>\n\n"
                f"Освобождено памяти: {memory_result['memory_freed_mb']} МБ\n"
                f"Очищено объектов: {memory_result['objects_cleaned']}\n"
                f"Сборка мусора: {memory_result['gc_collected']} объектов\n\n"
                f"Память до: {memory_result['memory_before_mb']} МБ\n"
                f"Память после: {memory_result['memory_after_mb']} МБ"
            )

            await safe_edit_text(status_msg, report, parse_mode="HTML")
            
        except Exception as e:
            logger.error(f"Ошибка в optimize_handler: {e}")
            await message.answer(f"❌ Ошибка при оптимизации: {e}")
    
    @router.message(Command("cleanup"))
    async def cleanup_handler(message: Message):
        """Обработчик команды /cleanup - управление очисткой файлов"""
        if not is_admin(message.from_user.id):
            await message.answer(ACCESS_DENIED)
            return
        
        if not CLEANUP_SERVICE_AVAILABLE:
            await message.answer("❌ Сервис очистки недоступен.")
            return
        
        try:
            # Получаем статистику
            stats = cleanup_service.get_cleanup_stats()
            report = admin_views.cleanup_stats_report(
                stats,
                interval_minutes=settings.cleanup_interval_minutes,
                temp_max_age_hours=settings.temp_file_max_age_hours,
                cache_max_age_hours=settings.cache_max_age_hours,
                cleanup_enabled=settings.enable_cleanup,
            )
            await safe_answer(message, report, parse_mode="HTML")

        except Exception as e:
            logger.error(f"Ошибка в cleanup_handler: {e}")
            await message.answer(_STATS_FAILED)
    
    @router.message(Command("cleanup_force"))
    async def cleanup_force_handler(message: Message):
        """Обработчик команды /cleanup_force - принудительная очистка"""
        if not is_admin(message.from_user.id):
            await message.answer(ACCESS_DENIED)
            return
        
        if not CLEANUP_SERVICE_AVAILABLE:
            await message.answer("❌ Сервис очистки недоступен.")
            return
        
        try:
            status_msg = await message.answer("⏳ Выполняю очистку")

            # Выполняем принудительную очистку
            cleaned_count = await cleanup_service.force_cleanup_all()

            # Получаем обновленную статистику
            stats = cleanup_service.get_cleanup_stats()
            report = admin_views.cleanup_done_report(cleaned_count, stats)

            await safe_edit_text(status_msg, report, parse_mode="HTML")

        except Exception as e:
            logger.error(f"Ошибка в cleanup_force_handler: {e}")
            await message.answer(f"❌ Ошибка при принудительной очистке: {e}")
    
    # ============================================================================
    # Обработчики callback-кнопок административного меню
    # ============================================================================
    
    @router.callback_query(F.data == "admin_status")
    async def admin_status_callback(callback: CallbackQuery):
        """Обработчик кнопки 'Статистика системы'"""
        if not is_admin(callback.from_user.id):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return
        
        try:
            await callback.answer()
            await safe_edit_text(callback.message, "⏳ Получаю статистику системы")

            report = monitoring_api.format_status_report()
            await safe_edit_text(callback.message, report, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка в admin_status_callback: {e}")
            await safe_edit_text(callback.message, f"❌ Ошибка при получении статуса: {e}")
    
    @router.callback_query(F.data == "admin_health")
    async def admin_health_callback(callback: CallbackQuery):
        """Обработчик кнопки 'Проверка здоровья'"""
        if not is_admin(callback.from_user.id):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return
        
        try:
            await callback.answer()
            await safe_edit_text(callback.message, "⏳ Проверяю здоровье системы")

            health_results = await health_checker.check_all()
            report = admin_views.health_report(health_results)
            await safe_edit_text(callback.message, report, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Ошибка в admin_health_callback: {e}")
            await safe_edit_text(callback.message, f"❌ Ошибка при проверке здоровья: {e}")
    
    @router.callback_query(F.data == "admin_performance")
    async def admin_performance_callback(callback: CallbackQuery):
        """Обработчик кнопки 'Производительность'"""
        if not is_admin(callback.from_user.id):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return
        
        try:
            from src.performance import memory_optimizer, metrics_collector, performance_cache, task_pool
            
            await callback.answer()
            await safe_edit_text(callback.message, "⏳ Собираю данные о производительности")

            # Собираем статистику
            cache_stats = performance_cache.get_stats()
            memory_stats = memory_optimizer.get_optimization_stats()
            task_stats = task_pool.get_stats()
            metrics_stats = metrics_collector.get_current_stats()

            report = admin_views.performance_report(
                cache_stats, memory_stats, task_stats, metrics_stats
            )
            await safe_edit_text(callback.message, report, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Ошибка в admin_performance_callback: {e}")
            await safe_edit_text(callback.message, _STATS_FAILED)
    
    @router.callback_query(F.data == "admin_cleanup")
    async def admin_cleanup_callback(callback: CallbackQuery):
        """Обработчик кнопки 'Управление файлами'"""
        if not is_admin(callback.from_user.id):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return
        
        try:
            await callback.answer()
            
            if not CLEANUP_SERVICE_AVAILABLE:
                await safe_edit_text(callback.message, "❌ Сервис очистки недоступен.")
                return

            # Получаем статистику
            stats = cleanup_service.get_cleanup_stats()
            report = admin_views.cleanup_stats_report(
                stats,
                interval_minutes=settings.cleanup_interval_minutes,
                temp_max_age_hours=settings.temp_file_max_age_hours,
                cache_max_age_hours=settings.cache_max_age_hours,
                cleanup_enabled=settings.enable_cleanup,
            )

            await safe_edit_text(callback.message, report, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Ошибка в admin_cleanup_callback: {e}")
            await safe_edit_text(callback.message, _STATS_FAILED)
    
    @router.callback_query(F.data == "admin_transcription")
    async def admin_transcription_callback(callback: CallbackQuery):
        """Обработчик кнопки 'Режим транскрипции'"""
        if not is_admin(callback.from_user.id):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return
        
        try:
            await callback.answer()

            text, keyboard = admin_views.transcription_mode_view(settings.transcription_mode)
            await safe_edit_text(
                callback.message, text, reply_markup=keyboard, parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Ошибка в admin_transcription_callback: {e}")
            await safe_edit_text(callback.message, f"❌ Ошибка при получении режимов транскрипции: {e}")
    
    @router.callback_query(F.data == "admin_reset")
    async def admin_reset_callback(callback: CallbackQuery):
        """Обработчик кнопки 'Сброс компонентов'"""
        if not is_admin(callback.from_user.id):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return
        
        try:
            await callback.answer()
            await safe_edit_text(callback.message, "⏳ Сбрасываю компоненты надежности")

            # Сбрасываем компоненты
            from src.llm import protocol_generator
            await protocol_generator.reset()
            await processing_service.reset_reliability_components()

            # Сбрасываем health checker
            for name, cb in health_checker.component_health.items():
                cb.consecutive_failures = 0
                cb.status = health_checker.HealthStatus.UNKNOWN

            await safe_edit_text(callback.message, "✅ Компоненты надежности сброшены успешно.")
        except Exception as e:
            logger.error(f"Ошибка в admin_reset_callback: {e}")
            await safe_edit_text(callback.message, f"❌ Ошибка при сбросе: {e}")
    
    @router.callback_query(F.data == "admin_export")
    async def admin_export_callback(callback: CallbackQuery):
        """Обработчик кнопки 'Экспорт статистики'"""
        if not is_admin(callback.from_user.id):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return
        
        try:
            await callback.answer()
            await safe_edit_text(callback.message, "⏳ Экспортирую статистику")

            # Экспортируем статистику
            json_stats = monitoring_api.export_stats_json()

            # Отправляем как файл
            file_input = BufferedInputFile(
                json_stats.encode('utf-8'),
                filename="bot_stats.json"
            )

            await callback.message.answer_document(
                file_input,
                caption="Экспорт статистики системы"
            )
            
            await callback.message.delete()
        except Exception as e:
            logger.error(f"Ошибка в admin_export_callback: {e}")
            await safe_edit_text(callback.message, f"❌ Ошибка при экспорте: {e}")
    
    @router.callback_query(F.data == "admin_help")
    async def admin_help_callback(callback: CallbackQuery):
        """Обработчик кнопки 'Справка'"""
        if not is_admin(callback.from_user.id):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return
        
        await callback.answer()

        await safe_edit_text(callback.message, admin_views.admin_help_text(), parse_mode="HTML")
    
    @router.callback_query(F.data == "admin_back_to_main")
    async def admin_back_to_main_callback(callback: CallbackQuery):
        """Обработчик кнопки 'Вернуться в главное меню'"""
        if not is_admin(callback.from_user.id):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return

        await callback.answer()

        from src.ux.quick_actions import QuickActionsUI

        # Показываем меню администратора заново
        keyboard = QuickActionsUI.create_admin_menu()
        await safe_edit_text(callback.message,
            "<b>Меню администратора</b>\n\n"
            "Выберите действие:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )

    # Управление пресетами модели — свой модуль: общего с мониторингом у него
    # только проверка прав, а объём был половиной этого файла.
    router.include_router(setup_admin_model_handlers())

    return router
