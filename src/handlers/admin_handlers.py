"""
Обработчики административных команд
"""

from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from loguru import logger

from api.monitoring import monitoring_api
from reliability.health_check import health_checker
from services.enhanced_llm_service import EnhancedLLMService
from services.optimized_processing_service import OptimizedProcessingService
from config import settings

# Импорт сервиса очистки
try:
    from src.services.cleanup_service import cleanup_service
    CLEANUP_SERVICE_AVAILABLE = True
except ImportError:
    CLEANUP_SERVICE_AVAILABLE = False


def setup_admin_handlers(llm_service: EnhancedLLMService, 
                        processing_service: OptimizedProcessingService) -> Router:
    """Настройка административных обработчиков"""
    router = Router()
    
    # Список ID администраторов (можно вынести в конфиг)
    ADMIN_IDS = getattr(settings, 'admin_ids', [])
    
    def is_admin(user_id: int) -> bool:
        """Проверить, является ли пользователь администратором"""
        return user_id in ADMIN_IDS if ADMIN_IDS else True  # Если админы не настроены, разрешаем всем
    
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
    
    return router
