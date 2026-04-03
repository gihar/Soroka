"""
Обработчики административных команд
"""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, BufferedInputFile
from aiogram.filters import Command
from loguru import logger

from api.monitoring import monitoring_api
from reliability.health_check import health_checker
from services.enhanced_llm_service import EnhancedLLMService
from services.processing_service import ProcessingService
from config import settings
from src.utils.admin_utils import is_admin
from src.utils.telegram_safe import safe_edit_text

# Импорт сервиса очистки
try:
    from src.services.cleanup_service import cleanup_service
    CLEANUP_SERVICE_AVAILABLE = True
except ImportError:
    CLEANUP_SERVICE_AVAILABLE = False


def setup_admin_handlers(llm_service: EnhancedLLMService, 
                        processing_service: ProcessingService) -> Router:
    """Настройка административных обработчиков"""
    router = Router()
    
    def escape_markdown(text: str) -> str:
        """Экранировать специальные символы Markdown"""
        # Экранируем символы, которые могут вызвать проблемы в Markdown
        escape_chars = ['*', '_', '`', '[', ']', '(', ')', '~', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for char in escape_chars:
            text = text.replace(char, f'\\{char}')
        return text
    
    @router.message(Command("status"))
    async def status_handler(message: Message):
        """Обработчик команды /status - статус системы"""
        if not is_admin(message.from_user.id):
            await message.answer("❌ Недостаточно прав для выполнения команды.")
            return
        
        try:
            report = monitoring_api.format_status_report()
            await message.answer(report, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка в status_handler: {e}")
            await message.answer(f"❌ Ошибка при получении статуса: {e}")
    
    @router.message(Command("health"))
    async def health_handler(message: Message):
        """Обработчик команды /health - детальная проверка здоровья"""
        if not is_admin(message.from_user.id):
            await message.answer("❌ Недостаточно прав для выполнения команды.")
            return
        
        try:
            # Запускаем проверку здоровья
            await message.answer("🔍 Выполняю проверку здоровья системы...")
            
            health_results = await health_checker.check_all()
            
            report_lines = ["🏥 **Детальная проверка здоровья**\n"]
            
            for component, result in health_results.items():
                status_emoji = {
                    "healthy": "✅",
                    "degraded": "⚠️",
                    "unhealthy": "❌",
                    "unknown": "❓"
                }.get(result.status.value, "❓")
                
                report_lines.append(f"**{component}:** {status_emoji} {result.status.value}")
                report_lines.append(f"  └ {result.message}")
                
                if result.response_time:
                    report_lines.append(f"  └ Время ответа: {result.response_time:.3f}с")
                
                report_lines.append("")
            
            report = "\n".join(report_lines)
            await message.answer(report, parse_mode="Markdown")
            
        except Exception as e:
            logger.error(f"Ошибка в health_handler: {e}")
            await message.answer(f"❌ Ошибка при проверке здоровья: {e}")
    
    @router.message(Command("stats"))
    async def stats_handler(message: Message):
        """Обработчик команды /stats - детальная статистика"""
        if not is_admin(message.from_user.id):
            await message.answer("❌ Недостаточно прав для выполнения команды.")
            return
        
        try:
            stats = monitoring_api.get_system_stats()
            
            # Форматируем статистику
            report_lines = ["📊 **Детальная статистика системы**\n"]
            
            # Производительность
            perf = stats.get("performance", {})
            if perf and "error" not in perf:
                report_lines.extend([
                    "**📈 Производительность:**",
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
                    "**🛡️ Rate Limiting:**",
                    f"• Всего запросов: {total_requests}",
                    f"• Заблокировано: {total_blocked}",
                    f"• Процент блокировки: {(total_blocked/max(1, total_requests))*100:.1f}%",
                    ""
                ])
            
            # Компоненты
            health = stats.get("health", {})
            components = health.get("components", {})
            if components:
                report_lines.append("**🔧 Статистика компонентов:**")
                for name, comp in components.items():
                    status = comp.get("status", "unknown")
                    checks = comp.get("total_checks", 0)
                    failures = comp.get("total_failures", 0)
                    failure_rate = comp.get("failure_rate", 0)
                    
                    report_lines.append(f"• **{name}:** {status}")
                    report_lines.append(f"  └ Проверок: {checks}, неудач: {failures} ({failure_rate:.1f}%)")
                
                report_lines.append("")
            
            report = "\n".join(report_lines)
            await message.answer(report, parse_mode="Markdown")
            
        except Exception as e:
            logger.error(f"Ошибка в stats_handler: {e}")
            await message.answer(f"❌ Ошибка при получении статистики: {e}")
    
    @router.message(Command("reset_reliability"))
    async def reset_reliability_handler(message: Message):
        """Обработчик команды /reset_reliability - сброс компонентов надежности"""
        if not is_admin(message.from_user.id):
            await message.answer("❌ Недостаточно прав для выполнения команды.")
            return
        
        try:
            await message.answer("🔄 Сбрасываю компоненты надежности...")
            
            # Сбрасываем компоненты
            await llm_service.reset_reliability_components()
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
            await message.answer("❌ Недостаточно прав для выполнения команды.")
            return
        
        try:
            # Экспортируем статистику
            json_stats = monitoring_api.export_stats_json()
            
            # Сохраняем во временный файл
            import tempfile
            import os
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
                f.write(json_stats)
                temp_path = f.name
            
            try:
                # Отправляем файл
                from aiogram.types import FSInputFile
                
                file_input = FSInputFile(temp_path, filename="bot_stats.json")
                await message.answer_document(
                    file_input,
                    caption="📊 Экспорт статистики системы"
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
            await message.answer("❌ Недостаточно прав для выполнения команды.")
            return
        
        try:
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
            
            # Создаем клавиатуру для выбора режима
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"{'✅ ' if settings.transcription_mode == 'local' else ''}🏠 Локальная (Whisper)",
                    callback_data="set_transcription_mode_local"
                )],
                [InlineKeyboardButton(
                    text=f"{'✅ ' if settings.transcription_mode == 'cloud' else ''}☁️ Облачная (Groq)",
                    callback_data="set_transcription_mode_cloud"
                )],
                [InlineKeyboardButton(
                    text=f"{'✅ ' if settings.transcription_mode == 'hybrid' else ''}🔄 Гибридная (Groq + диаризация)",
                    callback_data="set_transcription_mode_hybrid"
                )],
                [InlineKeyboardButton(
                    text=f"{'✅ ' if settings.transcription_mode == 'speechmatics' else ''}🎯 Speechmatics",
                    callback_data="set_transcription_mode_speechmatics"
                )],
                [InlineKeyboardButton(
                    text=f"{'✅ ' if settings.transcription_mode == 'deepgram' else ''}🎤 Deepgram",
                    callback_data="set_transcription_mode_deepgram"
                )],
                [InlineKeyboardButton(
                    text=f"{'✅ ' if settings.transcription_mode == 'leopard' else ''}🐆 Leopard (Picovoice)",
                    callback_data="set_transcription_mode_leopard"
                )]
            ])
            
            current_mode = settings.transcription_mode
            mode_descriptions = {
                "local": "Локальная транскрипция через Whisper",
                "cloud": "Облачная транскрипция через Groq API",
                "hybrid": "Гибридная: облачная транскрипция + локальная диаризация",
                "speechmatics": "Транскрипция и диаризация через Speechmatics API",
                "deepgram": "Транскрипция и диаризация через Deepgram API",
                "leopard": "Локальная транскрипция через Picovoice Leopard"
            }
            
            current_description = mode_descriptions.get(current_mode, "Неизвестный режим")
            
            await message.answer(
                f"🎙️ **Текущий режим транскрипции:** {current_mode}\n"
                f"📝 **Описание:** {current_description}\n\n"
                f"Выберите новый режим:",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            
        except Exception as e:
            logger.error(f"Ошибка в transcription_mode_handler: {e}")
            await message.answer(f"❌ Ошибка при получении режимов транскрипции: {e}")
    
    @router.message(Command("admin_help"))
    async def admin_help_handler(message: Message):
        """Обработчик команды /admin_help - справка по административным командам"""
        if not is_admin(message.from_user.id):
            await message.answer("❌ Недостаточно прав для выполнения команды.")
            return
        
        help_text = """
🔧 **Административные команды**

**Мониторинг:**
• `/status` - общий статус системы
• `/health` - детальная проверка здоровья
• `/stats` - детальная статистика
• `/export_stats` - экспорт статистики в JSON

**Производительность:**
• `/performance` - статистика производительности
• `/optimize` - принудительная оптимизация памяти

**Управление:**
• `/reset_reliability` - сброс компонентов надежности
• `/transcription_mode` - переключение режима транскрипции

**Управление моделями:**
• `/models` - список моделей с inline-управлением
• `/add_model` - добавить модель

**Очистка файлов:**
• `/cleanup` - статистика файлов и настройки очистки
• `/cleanup_force` - принудительная очистка всех временных файлов

**Справка:**
• `/admin_help` - эта справка

**Примечание:** Административные команды доступны только авторизованным пользователям.
        """

        await message.answer(help_text, parse_mode="Markdown")

    @router.message(Command("performance"))
    async def performance_handler(message: Message):
        """Обработчик команды /performance - статистика производительности"""
        if not is_admin(message.from_user.id):
            await message.answer("❌ Недостаточно прав для выполнения команды.")
            return
        
        try:
            from performance import (
                performance_cache, metrics_collector, memory_optimizer, task_pool
            )
            
            # Собираем статистику
            cache_stats = performance_cache.get_stats()
            memory_stats = memory_optimizer.get_optimization_stats()
            task_stats = task_pool.get_stats()
            metrics_stats = metrics_collector.get_current_stats()
            
            # Форматируем отчет
            report = (
                "📊 **Статистика производительности**\n\n"
                
                "💾 **Кэш:**\n"
                f"• Hit Rate: {cache_stats['hit_rate_percent']}%\n"
                f"• Память: {cache_stats['memory_usage_mb']}MB "
                f"({cache_stats['memory_usage_percent']}%)\n"
                f"• Записей: {cache_stats['memory_entries']} + {cache_stats['disk_entries']} (диск)\n\n"
                
                "🧠 **Память:**\n"
                f"• Система: {memory_stats['current_memory']['percent']}%\n"
                f"• Процесс: {memory_stats['current_memory']['process_mb']:.1f}MB\n"
                f"• Автооптимизация: {'Вкл' if memory_stats['is_optimizing'] else 'Выкл'}\n\n"
                
                "⚡ **Задачи:**\n"
                f"• Активные: {task_stats['active_tasks']}\n"
                f"• Макс параллельно: {task_stats['max_concurrent']}\n"
                f"• Успешность: {task_stats['success_rate']:.1f}%\n\n"
                
                "📈 **Обработка:**\n"
                f"• Запросов за час: {metrics_stats['processing']['requests_1h']}\n"
                f"• Успешность: {metrics_stats['processing']['success_rate_percent']}%\n"
                f"• Среднее время: {metrics_stats['processing']['avg_duration_seconds']}с\n"
                f"• Эффективность: {metrics_stats['processing']['avg_efficiency_ratio']}\n"
            )
            
            await message.answer(report, parse_mode="Markdown")
            
        except Exception as e:
            logger.error(f"Ошибка в performance_handler: {e}")
            await message.answer(f"❌ Ошибка при получении статистики: {e}")
    
    @router.message(Command("optimize"))
    async def optimize_handler(message: Message):
        """Обработчик команды /optimize - принудительная оптимизация"""
        if not is_admin(message.from_user.id):
            await message.answer("❌ Недостаточно прав для выполнения команды.")
            return
        
        try:
            from performance import memory_optimizer, performance_cache
            
            status_msg = await message.answer("🔄 Выполняю оптимизацию...")
            
            # Оптимизация памяти
            memory_result = await memory_optimizer.optimize_memory()
            
            # Очистка кэша
            await performance_cache.cleanup_expired()
            
            # Отчет об оптимизации
            report = (
                "✅ **Оптимизация завершена**\n\n"
                f"💾 Освобождено памяти: {memory_result['memory_freed_mb']}MB\n"
                f"🧹 Очищено объектов: {memory_result['objects_cleaned']}\n"
                f"♻️ Сборка мусора: {memory_result['gc_collected']} объектов\n\n"
                f"📊 Память до: {memory_result['memory_before_mb']}MB\n"
                f"📊 Память после: {memory_result['memory_after_mb']}MB"
            )
            
            await status_msg.edit_text(report, parse_mode="Markdown")
            
        except Exception as e:
            logger.error(f"Ошибка в optimize_handler: {e}")
            await message.answer(f"❌ Ошибка при оптимизации: {e}")
    
    @router.message(Command("cleanup"))
    async def cleanup_handler(message: Message):
        """Обработчик команды /cleanup - управление очисткой файлов"""
        if not is_admin(message.from_user.id):
            await message.answer("❌ Недостаточно прав для выполнения команды.")
            return
        
        if not CLEANUP_SERVICE_AVAILABLE:
            await message.answer("❌ Сервис очистки недоступен.")
            return
        
        try:
            # Получаем статистику
            stats = cleanup_service.get_cleanup_stats()
            
            # Формируем отчет
            report = (
                "📁 Статистика файлов\n\n"
                f"📂 Временные файлы: {stats['temp_files']} ({stats['temp_size_mb']:.1f}MB)\n"
                f"🗂️ Кэш файлы: {stats['cache_files']} ({stats['cache_size_mb']:.1f}MB)\n\n"
                f"⏰ Старые временные файлы: {stats['old_temp_files']}\n"
                f"⏰ Старые кэш файлы: {stats['old_cache_files']}\n\n"
                f"⚙️ Настройки:\n"
                f"• Интервал очистки: {settings.cleanup_interval_minutes} мин\n"
                f"• Макс. возраст временных файлов: {settings.temp_file_max_age_hours} ч\n"
                f"• Макс. возраст кэш файлов: {settings.cache_max_age_hours} ч\n"
                f"• Автоочистка: {'✅' if settings.enable_cleanup else '❌'}\n\n"
                "Используйте /cleanup_force для принудительной очистки"
            )
            
            await message.answer(report)
            
        except Exception as e:
            logger.error(f"Ошибка в cleanup_handler: {e}")
            await message.answer(f"❌ Ошибка при получении статистики: {e}")
    
    @router.message(Command("cleanup_force"))
    async def cleanup_force_handler(message: Message):
        """Обработчик команды /cleanup_force - принудительная очистка"""
        if not is_admin(message.from_user.id):
            await message.answer("❌ Недостаточно прав для выполнения команды.")
            return
        
        if not CLEANUP_SERVICE_AVAILABLE:
            await message.answer("❌ Сервис очистки недоступен.")
            return
        
        try:
            status_msg = await message.answer("🧹 Выполняю принудительную очистку...")
            
            # Выполняем принудительную очистку
            cleaned_count = await cleanup_service.force_cleanup_all()
            
            # Получаем обновленную статистику
            stats = cleanup_service.get_cleanup_stats()
            
            report = (
                "✅ Принудительная очистка завершена\n\n"
                f"🗑️ Удалено файлов: {cleaned_count}\n\n"
                f"📊 Текущее состояние:\n"
                f"• Временные файлы: {stats['temp_files']} ({stats['temp_size_mb']:.1f}MB)\n"
                f"• Кэш файлы: {stats['cache_files']} ({stats['cache_size_mb']:.1f}MB)"
            )
            
            await status_msg.edit_text(report)
            
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
            await safe_edit_text(callback.message, "🔄 Получаю статистику системы...")
            
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
            await safe_edit_text(callback.message, "🔍 Выполняю проверку здоровья системы...")
            
            health_results = await health_checker.check_all()
            
            report_lines = ["🏥 **Детальная проверка здоровья**\n"]
            
            for component, result in health_results.items():
                status_emoji = {
                    "healthy": "✅",
                    "degraded": "⚠️",
                    "unhealthy": "❌",
                    "unknown": "❓"
                }.get(result.status.value, "❓")
                
                report_lines.append(f"**{component}:** {status_emoji} {result.status.value}")
                report_lines.append(f"  └ {result.message}")
                
                if result.response_time:
                    report_lines.append(f"  └ Время ответа: {result.response_time:.3f}с")
                
                report_lines.append("")
            
            report = "\n".join(report_lines)
            await safe_edit_text(callback.message, report, parse_mode="Markdown")
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
            from performance import (
                performance_cache, metrics_collector, memory_optimizer, task_pool
            )
            
            await callback.answer()
            await safe_edit_text(callback.message, "📊 Собираю данные о производительности...")
            
            # Собираем статистику
            cache_stats = performance_cache.get_stats()
            memory_stats = memory_optimizer.get_optimization_stats()
            task_stats = task_pool.get_stats()
            metrics_stats = metrics_collector.get_current_stats()
            
            # Форматируем отчет
            report = (
                "📊 **Статистика производительности**\n\n"
                
                "💾 **Кэш:**\n"
                f"• Hit Rate: {cache_stats['hit_rate_percent']}%\n"
                f"• Память: {cache_stats['memory_usage_mb']}MB "
                f"({cache_stats['memory_usage_percent']}%)\n"
                f"• Записей: {cache_stats['memory_entries']} + {cache_stats['disk_entries']} (диск)\n\n"
                
                "🧠 **Память:**\n"
                f"• Система: {memory_stats['current_memory']['percent']}%\n"
                f"• Процесс: {memory_stats['current_memory']['process_mb']:.1f}MB\n"
                f"• Автооптимизация: {'Вкл' if memory_stats['is_optimizing'] else 'Выкл'}\n\n"
                
                "⚡ **Задачи:**\n"
                f"• Активные: {task_stats['active_tasks']}\n"
                f"• Макс параллельно: {task_stats['max_concurrent']}\n"
                f"• Успешность: {task_stats['success_rate']:.1f}%\n\n"
                
                "📈 **Обработка:**\n"
                f"• Запросов за час: {metrics_stats['processing']['requests_1h']}\n"
                f"• Успешность: {metrics_stats['processing']['success_rate_percent']}%\n"
                f"• Среднее время: {metrics_stats['processing']['avg_duration_seconds']}с\n"
                f"• Эффективность: {metrics_stats['processing']['avg_efficiency_ratio']}\n"
            )
            
            await safe_edit_text(callback.message, report, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка в admin_performance_callback: {e}")
            await safe_edit_text(callback.message, f"❌ Ошибка при получении статистики: {e}")
    
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
            
            # Формируем отчет
            report = (
                "📁 **Статистика файлов**\n\n"
                f"📂 Временные файлы: {stats['temp_files']} ({stats['temp_size_mb']:.1f}MB)\n"
                f"🗂️ Кэш файлы: {stats['cache_files']} ({stats['cache_size_mb']:.1f}MB)\n\n"
                f"⏰ Старые временные файлы: {stats['old_temp_files']}\n"
                f"⏰ Старые кэш файлы: {stats['old_cache_files']}\n\n"
                f"⚙️ **Настройки:**\n"
                f"• Интервал очистки: {settings.cleanup_interval_minutes} мин\n"
                f"• Макс. возраст временных файлов: {settings.temp_file_max_age_hours} ч\n"
                f"• Макс. возраст кэш файлов: {settings.cache_max_age_hours} ч\n"
                f"• Автоочистка: {'✅' if settings.enable_cleanup else '❌'}\n\n"
                "Используйте команду /cleanup_force для принудительной очистки"
            )
            
            await safe_edit_text(callback.message, report, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка в admin_cleanup_callback: {e}")
            await safe_edit_text(callback.message, f"❌ Ошибка при получении статистики: {e}")
    
    @router.callback_query(F.data == "admin_transcription")
    async def admin_transcription_callback(callback: CallbackQuery):
        """Обработчик кнопки 'Режим транскрипции'"""
        if not is_admin(callback.from_user.id):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return
        
        try:
            await callback.answer()
            
            # Создаем клавиатуру для выбора режима
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"{'✅ ' if settings.transcription_mode == 'local' else ''}🏠 Локальная (Whisper)",
                    callback_data="set_transcription_mode_local"
                )],
                [InlineKeyboardButton(
                    text=f"{'✅ ' if settings.transcription_mode == 'cloud' else ''}☁️ Облачная (Groq)",
                    callback_data="set_transcription_mode_cloud"
                )],
                [InlineKeyboardButton(
                    text=f"{'✅ ' if settings.transcription_mode == 'hybrid' else ''}🔄 Гибридная (Groq + диаризация)",
                    callback_data="set_transcription_mode_hybrid"
                )],
                [InlineKeyboardButton(
                    text=f"{'✅ ' if settings.transcription_mode == 'speechmatics' else ''}🎯 Speechmatics",
                    callback_data="set_transcription_mode_speechmatics"
                )],
                [InlineKeyboardButton(
                    text=f"{'✅ ' if settings.transcription_mode == 'deepgram' else ''}🎤 Deepgram",
                    callback_data="set_transcription_mode_deepgram"
                )],
                [InlineKeyboardButton(
                    text=f"{'✅ ' if settings.transcription_mode == 'leopard' else ''}🐆 Leopard (Picovoice)",
                    callback_data="set_transcription_mode_leopard"
                )]
            ])
            
            current_mode = settings.transcription_mode
            mode_descriptions = {
                "local": "Локальная транскрипция через Whisper",
                "cloud": "Облачная транскрипция через Groq API",
                "hybrid": "Гибридная: облачная транскрипция + локальная диаризация",
                "speechmatics": "Транскрипция и диаризация через Speechmatics API",
                "deepgram": "Транскрипция и диаризация через Deepgram API",
                "leopard": "Локальная транскрипция через Picovoice Leopard"
            }
            
            current_description = mode_descriptions.get(current_mode, "Неизвестный режим")
            
            await safe_edit_text(callback.message, 
                f"🎙️ **Текущий режим транскрипции:** {current_mode}\n"
                f"📝 **Описание:** {current_description}\n\n"
                f"Выберите новый режим:",
                reply_markup=keyboard,
                parse_mode="Markdown"
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
            await safe_edit_text(callback.message, "🔄 Сбрасываю компоненты надежности...")
            
            # Сбрасываем компоненты
            await llm_service.reset_reliability_components()
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
            await safe_edit_text(callback.message, "📥 Экспортирую статистику...")
            
            # Экспортируем статистику
            json_stats = monitoring_api.export_stats_json()
            
            # Отправляем как файл
            file_input = BufferedInputFile(
                json_stats.encode('utf-8'),
                filename="bot_stats.json"
            )
            
            await callback.message.answer_document(
                file_input,
                caption="📊 Экспорт статистики системы"
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
        
        help_text = """
🔧 **Административные команды**

**Мониторинг:**
• `/status` - общий статус системы
• `/health` - детальная проверка здоровья
• `/stats` - детальная статистика
• `/export_stats` - экспорт статистики в JSON

**Производительность:**
• `/performance` - статистика производительности
• `/optimize` - принудительная оптимизация памяти

**Управление:**
• `/reset_reliability` - сброс компонентов надежности
• `/transcription_mode` - переключение режима транскрипции

**Управление моделями:**
• `/models` - список моделей с inline-управлением
• `/add_model` - добавить модель

**Очистка файлов:**
• `/cleanup` - статистика файлов и настройки очистки
• `/cleanup_force` - принудительная очистка всех временных файлов

**Справка:**
• `/admin_help` - эта справка

**Примечание:** Административные команды доступны только авторизованным пользователям.
        """

        await safe_edit_text(callback.message, help_text, parse_mode="Markdown")
    
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
            "🔧 **Меню администратора**\n\n"
            "Выберите действие:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

    # ============================================================================
    # Управление моделями — /add_model, /models и inline-обработчики
    # ============================================================================

    async def _render_models_list(presets):
        """Build text and keyboard for the models list view."""
        if not presets:
            text = "📋 **Список моделей**\n\nМоделей пока нет. Используйте /add\\_model или синхронизируйте из .env."
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="🔄 Синхр. из .env",
                    callback_data="admin_models_sync",
                )],
            ])
            return text, keyboard

        lines = ["📋 **Список моделей**\n"]
        buttons = []
        for p in presets:
            if not p.get("is_enabled"):
                icon = "⛔"
            elif p.get("admin_only"):
                icon = "🔒"
            else:
                icon = "✅"
            lines.append(f"{icon} {p['name']}")
            buttons.append([InlineKeyboardButton(
                text=f"{icon} {p['name']}",
                callback_data=f"admin_model_{p['key']}",
            )])

        buttons.append([InlineKeyboardButton(
            text="🔄 Синхр. из .env",
            callback_data="admin_models_sync",
        )])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        text = "\n".join(lines)
        return text, keyboard

    async def _render_model_detail(preset):
        """Build text and keyboard for a single model detail card."""
        key = preset["key"]
        api_key_status = "✅ задан" if preset.get("api_key") else "❌ не задан"
        enabled_label = "✅ включена" if preset.get("is_enabled") else "⛔ выключена"
        access_label = "🔒 только админы" if preset.get("admin_only") else "👥 все пользователи"

        text = (
            f"🤖 **{preset['name']}**\n\n"
            f"**Key:** `{key}`\n"
            f"**Model ID:** `{preset['model']}`\n"
            f"**Base URL:** `{preset['base_url']}`\n"
            f"**API Key:** {api_key_status}\n"
            f"**Статус:** {enabled_label}\n"
            f"**Доступ:** {access_label}"
        )

        toggle_text = "⛔ Выключить" if preset.get("is_enabled") else "✅ Включить"
        access_text = "👥 Для всех" if preset.get("admin_only") else "🔒 Только админы"

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=toggle_text, callback_data=f"admin_model_toggle_{key}"),
                InlineKeyboardButton(text=access_text, callback_data=f"admin_model_access_{key}"),
            ],
            [
                InlineKeyboardButton(text="🗑 Удалить", callback_data=f"admin_model_delete_{key}"),
                InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_models_list"),
            ],
        ])
        return text, keyboard

    @router.message(Command("add_model"))
    async def add_model_handler(message: Message):
        """Добавление модели: /add_model model_id \"Name\" base_url [api_key]"""
        if not is_admin(message.from_user.id):
            await message.answer("❌ Недостаточно прав для выполнения команды.")
            return

        import re
        from database import db
        from src.database.model_preset_repo import ModelPresetRepository

        raw_args = (message.text or "").split(maxsplit=1)
        args_str = raw_args[1].strip() if len(raw_args) > 1 else ""

        if not args_str:
            await message.answer(
                "📖 **Использование:**\n"
                "`/add_model model_id \"Название\" base_url [api_key]`\n\n"
                "**Пример:**\n"
                '`/add_model gpt-4o "GPT-4o" https://api.openai.com/v1 sk-xxx`',
                parse_mode="Markdown",
            )
            return

        pattern = r'(\S+)\s+"([^"]+)"\s+(\S+)(?:\s+(\S+))?'
        match = re.match(pattern, args_str)
        if not match:
            await message.answer(
                "❌ Неверный формат. Используйте:\n"
                "`/add_model model_id \"Название\" base_url [api_key]`",
                parse_mode="Markdown",
            )
            return

        model_id = match.group(1)
        name = match.group(2)
        base_url = match.group(3)
        api_key = match.group(4)  # may be None

        key = re.sub(r'[^a-zA-Z0-9_-]', '_', model_id)

        try:
            repo = ModelPresetRepository(db)
            await repo.upsert(key, name, model_id, base_url, api_key)

            api_display = "задан" if api_key else "не задан (используется существующий)"
            await message.answer(
                f"✅ Модель добавлена/обновлена\n\n"
                f"**Key:** `{key}`\n"
                f"**Название:** {name}\n"
                f"**Model ID:** `{model_id}`\n"
                f"**Base URL:** `{base_url}`\n"
                f"**API Key:** {api_display}",
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Ошибка в add_model_handler: {e}")
            await message.answer(f"❌ Ошибка при добавлении модели: {e}")

    @router.message(Command("models"))
    async def models_handler(message: Message):
        """Список всех моделей с inline-кнопками."""
        if not is_admin(message.from_user.id):
            await message.answer("❌ Недостаточно прав для выполнения команды.")
            return

        try:
            from database import db
            from src.database.model_preset_repo import ModelPresetRepository

            repo = ModelPresetRepository(db)
            presets = await repo.get_all()
            text, keyboard = await _render_models_list(presets)
            await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка в models_handler: {e}")
            await message.answer(f"❌ Ошибка при получении списка моделей: {e}")

    @router.callback_query(F.data.startswith("admin_model_toggle_"))
    async def admin_model_toggle_callback(callback: CallbackQuery):
        """Переключить is_enabled для модели."""
        if not is_admin(callback.from_user.id):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return

        try:
            from database import db
            from src.database.model_preset_repo import ModelPresetRepository

            await callback.answer()
            key = callback.data.replace("admin_model_toggle_", "", 1)
            repo = ModelPresetRepository(db)
            preset = await repo.get_by_key(key)
            if not preset:
                await safe_edit_text(callback.message, f"❌ Модель `{key}` не найдена.", parse_mode="Markdown")
                return

            new_value = 0 if preset.get("is_enabled") else 1
            await repo.update_field(key, "is_enabled", new_value)

            updated = await repo.get_by_key(key)
            text, keyboard = await _render_model_detail(updated)
            await safe_edit_text(callback.message, text, reply_markup=keyboard, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка в admin_model_toggle_callback: {e}")
            await safe_edit_text(callback.message, f"❌ Ошибка: {e}")

    @router.callback_query(F.data.startswith("admin_model_access_"))
    async def admin_model_access_callback(callback: CallbackQuery):
        """Переключить admin_only для модели."""
        if not is_admin(callback.from_user.id):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return

        try:
            from database import db
            from src.database.model_preset_repo import ModelPresetRepository

            await callback.answer()
            key = callback.data.replace("admin_model_access_", "", 1)
            repo = ModelPresetRepository(db)
            preset = await repo.get_by_key(key)
            if not preset:
                await safe_edit_text(callback.message, f"❌ Модель `{key}` не найдена.", parse_mode="Markdown")
                return

            new_value = 0 if preset.get("admin_only") else 1
            await repo.update_field(key, "admin_only", new_value)

            updated = await repo.get_by_key(key)
            text, keyboard = await _render_model_detail(updated)
            await safe_edit_text(callback.message, text, reply_markup=keyboard, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка в admin_model_access_callback: {e}")
            await safe_edit_text(callback.message, f"❌ Ошибка: {e}")

    @router.callback_query(F.data.startswith("admin_model_delete_"))
    async def admin_model_delete_callback(callback: CallbackQuery):
        """Удалить модель и вернуться к списку."""
        if not is_admin(callback.from_user.id):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return

        try:
            from database import db
            from src.database.model_preset_repo import ModelPresetRepository

            await callback.answer()
            key = callback.data.replace("admin_model_delete_", "", 1)
            repo = ModelPresetRepository(db)
            deleted = await repo.delete(key)

            if not deleted:
                await safe_edit_text(callback.message, f"❌ Модель `{key}` не найдена.", parse_mode="Markdown")
                return

            presets = await repo.get_all()
            text, keyboard = await _render_models_list(presets)
            text = f"🗑 Модель `{key}` удалена.\n\n{text}"
            await safe_edit_text(callback.message, text, reply_markup=keyboard, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка в admin_model_delete_callback: {e}")
            await safe_edit_text(callback.message, f"❌ Ошибка: {e}")

    @router.callback_query(F.data.startswith("admin_model_"))
    async def admin_model_detail_callback(callback: CallbackQuery):
        """Карточка модели (детальный просмотр)."""
        if not is_admin(callback.from_user.id):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return

        try:
            from database import db
            from src.database.model_preset_repo import ModelPresetRepository

            await callback.answer()
            key = callback.data.replace("admin_model_", "", 1)
            repo = ModelPresetRepository(db)
            preset = await repo.get_by_key(key)
            if not preset:
                await safe_edit_text(callback.message, f"❌ Модель `{key}` не найдена.", parse_mode="Markdown")
                return

            text, keyboard = await _render_model_detail(preset)
            await safe_edit_text(callback.message, text, reply_markup=keyboard, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка в admin_model_detail_callback: {e}")
            await safe_edit_text(callback.message, f"❌ Ошибка: {e}")

    @router.callback_query(F.data == "admin_models_sync")
    async def admin_models_sync_callback(callback: CallbackQuery):
        """Синхронизировать модели из .env конфига."""
        if not is_admin(callback.from_user.id):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return

        try:
            from database import db
            from src.database.model_preset_repo import ModelPresetRepository

            await callback.answer()
            repo = ModelPresetRepository(db)
            count = await repo.sync_from_config()

            presets = await repo.get_all()
            text, keyboard = await _render_models_list(presets)
            text = f"🔄 Синхронизировано моделей: {count}\n\n{text}"
            await safe_edit_text(callback.message, text, reply_markup=keyboard, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка в admin_models_sync_callback: {e}")
            await safe_edit_text(callback.message, f"❌ Ошибка синхронизации: {e}")

    @router.callback_query(F.data == "admin_models_list")
    async def admin_models_list_callback(callback: CallbackQuery):
        """Вернуться к списку моделей (inline)."""
        if not is_admin(callback.from_user.id):
            await callback.answer("❌ Недостаточно прав", show_alert=True)
            return

        try:
            from database import db
            from src.database.model_preset_repo import ModelPresetRepository

            await callback.answer()
            repo = ModelPresetRepository(db)
            presets = await repo.get_all()
            text, keyboard = await _render_models_list(presets)
            await safe_edit_text(callback.message, text, reply_markup=keyboard, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка в admin_models_list_callback: {e}")
            await safe_edit_text(callback.message, f"❌ Ошибка: {e}")

    return router
