"""
Бот с улучшенной системой надежности и обработки ошибок
"""

import asyncio
import os
from loguru import logger
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import settings
from database import db

# Импорты надежности
from reliability import health_checker
from reliability.middleware import (
    error_handling_middleware,
    monitoring_middleware, 
    rate_limiting_middleware,
    health_check_middleware
)

# Импорты новой архитектуры
from services import (
    UserService, TemplateService, FileService, 
    EnhancedLLMService, OptimizedProcessingService
)
from handlers import (
    setup_command_handlers, setup_callback_handlers,
    setup_message_handlers, setup_template_handlers
)
from handlers.admin_handlers import setup_admin_handlers
from exceptions import BotException


class EnhancedTelegramBot:
    """Бот с улучшенной системой надежности"""
    
    def __init__(self):
        self.bot = Bot(token=settings.telegram_token)
        self.dp = Dispatcher(storage=MemoryStorage())
        
        # Инициализация сервисов
        self.user_service = UserService()
        self.template_service = TemplateService()
        self.file_service = FileService()
        self.llm_service = EnhancedLLMService()
        self.processing_service = OptimizedProcessingService()
        
        # Настройка middleware и обработчиков
        self._setup_middleware()
        self._setup_handlers()
        self._setup_error_handling()
    
    def _setup_middleware(self):
        """Настройка middleware для надежности"""
        # Порядок middleware важен!
        
        # 1. Мониторинг (должен быть первым для корректного измерения времени)
        self.dp.message.middleware(monitoring_middleware)
        self.dp.callback_query.middleware(monitoring_middleware)
        
        # 2. Health Check
        self.dp.message.middleware(health_check_middleware)
        self.dp.callback_query.middleware(health_check_middleware)
        
        # 3. Rate Limiting
        self.dp.message.middleware(rate_limiting_middleware)
        
        # 4. Error Handling (должен быть последним для перехвата всех ошибок)
        self.dp.message.middleware(error_handling_middleware)
        self.dp.callback_query.middleware(error_handling_middleware)
        
        logger.info("Middleware для надежности настроены")
    
    def _setup_handlers(self):
        """Настройка всех обработчиков"""
        # Команды
        command_router = setup_command_handlers(
            self.user_service, self.template_service, self.llm_service
        )
        self.dp.include_router(command_router)
        
        # UX обработчики - быстрые действия (ДОЛЖНЫ БЫТЬ РАНЬШЕ message_handlers!)
        from ux import setup_quick_actions_handlers, setup_feedback_handlers, feedback_collector
        
        quick_actions_router = setup_quick_actions_handlers()
        self.dp.include_router(quick_actions_router)
        
        # Callback запросы - используем enhanced сервисы
        callback_router = setup_callback_handlers(
            self.user_service, self.template_service, self.llm_service, self.processing_service
        )
        self.dp.include_router(callback_router)
        
        # Сообщения с файлами - используем enhanced сервисы (ПОСЛЕ quick_actions!)
        message_router = setup_message_handlers(
            self.file_service, self.template_service, self.processing_service
        )
        self.dp.include_router(message_router)
        
        # Обработчики шаблонов
        template_router = setup_template_handlers(
            self.template_service
        )
        self.dp.include_router(template_router)
        
        # Административные обработчики
        admin_router = setup_admin_handlers(
            self.llm_service, self.processing_service
        )
        self.dp.include_router(admin_router)
        
        feedback_router = setup_feedback_handlers(feedback_collector)
        self.dp.include_router(feedback_router)
        
        # Обработчики быстрой обратной связи
        from ux.feedback_system import QuickFeedbackManager
        quick_feedback_manager = QuickFeedbackManager(feedback_collector)
        quick_feedback_router = quick_feedback_manager.create_feedback_handlers()
        self.dp.include_router(quick_feedback_router)
    
    def _setup_error_handling(self):
        """Настройка дополнительной обработки ошибок"""
        @self.dp.error()
        async def error_handler(update, exception):
            """Глобальный обработчик ошибок"""
            logger.error(f"Необработанная ошибка в update {update.update_id}: {exception}")
            
            # Дополнительная логика для критических ошибок
            if "database" in str(exception).lower():
                logger.critical("Проблемы с базой данных обнаружены")
                # Можно добавить алерты или автоматическое восстановление
            
            return True  # Помечаем ошибку как обработанную
    
    async def start(self):
        """Запустить бота с системой надежности"""
        try:
            logger.info("Запуск бота с системой надежности...")
            
            # 1. Инициализируем базу данных
            await db.init_db()
            logger.info("База данных инициализирована")
            
            # 2. Инициализируем базовые шаблоны
            await self.template_service.init_default_templates()
            logger.info("Базовые шаблоны инициализированы")
            
            # 3. Создаем директорию для временных файлов
            os.makedirs(settings.temp_dir, exist_ok=True)
            logger.info(f"Директория для временных файлов создана: {settings.temp_dir}")
            
            # 4. Запускаем мониторинг здоровья
            await health_checker.start_monitoring()
            logger.info("Мониторинг здоровья запущен")
            
            # 5. Проверяем доступность компонентов
            await self._perform_startup_checks()
            
            # 6. Запускаем бота
            logger.info("Бот с системой надежности запущен и готов к работе")
            await self.dp.start_polling(self.bot)
            
        except Exception as e:
            logger.error(f"Критическая ошибка при запуске бота: {e}")
            await self.emergency_shutdown()
            raise
    
    async def _perform_startup_checks(self):
        """Выполнить проверки при запуске"""
        logger.info("Выполнение проверок при запуске...")
        
        # Проверяем здоровье всех компонентов
        health_results = await health_checker.check_all()
        
        critical_issues = []
        warnings = []
        
        for component, result in health_results.items():
            if result.status.value == "unhealthy":
                critical_issues.append(f"{component}: {result.message}")
            elif result.status.value == "degraded":
                warnings.append(f"{component}: {result.message}")
        
        if critical_issues:
            logger.error("Критические проблемы при запуске:")
            for issue in critical_issues:
                logger.error(f"  - {issue}")
            # Не останавливаем запуск, но уведомляем
        
        if warnings:
            logger.warning("Предупреждения при запуске:")
            for warning in warnings:
                logger.warning(f"  - {warning}")
        
        # Проверяем доступность LLM провайдеров
        available_providers = self.llm_service.get_available_providers()
        logger.info(f"Доступные LLM провайдеры: {list(available_providers.keys())}")
        
        if not available_providers:
            logger.error("Нет доступных LLM провайдеров!")
        
        logger.info("Проверки при запуске завершены")
    
    async def stop(self):
        """Остановить бота с graceful shutdown"""
        try:
            logger.info("Начало graceful shutdown...")
            
            # 1. Останавливаем мониторинг здоровья
            await health_checker.stop_monitoring()
            logger.info("Мониторинг здоровья остановлен")
            
            # 2. Даем время завершить текущие операции
            await asyncio.sleep(1)
            
            # 3. Закрываем соединение с ботом
            await self.bot.session.close()
            logger.info("Соединение с ботом закрыто")
            
            # 3.1. Даем время на очистку всех aiohttp сессий
            await asyncio.sleep(0.5)
            
            # 3.2. Принудительная очистка всех открытых aiohttp сессий
            try:
                import gc
                import aiohttp
                for obj in gc.get_objects():
                    if isinstance(obj, aiohttp.ClientSession) and not obj.closed:
                        await obj.close()
                        logger.debug("Закрыта открытая aiohttp сессия")
            except Exception as e:
                logger.debug(f"Ошибка при принудительной очистке сессий: {e}")
            
            # 4. Сохраняем статистику
            await self._save_shutdown_stats()
            
            logger.info("Graceful shutdown завершен")
            
        except Exception as e:
            logger.error(f"Ошибка при graceful shutdown: {e}")
            await self.emergency_shutdown()
    
    async def emergency_shutdown(self):
        """Экстренное завершение работы"""
        try:
            logger.critical("Выполнение экстренного завершения работы")
            
            # Принудительно останавливаем критические компоненты
            try:
                await health_checker.stop_monitoring()
            except:
                pass
            
            try:
                await self.bot.session.close()
            except:
                pass
            
            logger.critical("Экстренное завершение работы выполнено")
            
        except Exception as e:
            logger.critical(f"Ошибка при экстренном завершении: {e}")
    
    async def _save_shutdown_stats(self):
        """Сохранить статистику при завершении"""
        try:
            stats = self.get_system_stats()
            logger.info("Статистика при завершении работы:")
            
            # Безопасное получение статистики мониторинга
            monitoring_stats = stats.get('monitoring', {})
            if isinstance(monitoring_stats, dict):
                total_requests = monitoring_stats.get('total_requests', 0)
                total_errors = monitoring_stats.get('total_errors', 0)
                avg_time = monitoring_stats.get('average_processing_time', 0.0)
                
                logger.info(f"  Всего запросов: {total_requests}")
                logger.info(f"  Ошибок: {total_errors}")
                logger.info(f"  Среднее время обработки: {avg_time:.3f}s")
            else:
                logger.info("  Статистика мониторинга недоступна")
            
            # Статистика надежности
            processing_stats = stats.get('processing', {})
            if isinstance(processing_stats, dict) and 'error' not in processing_stats:
                logger.info("  Статистика обработки: Доступна")
            else:
                logger.info("  Статистика обработки: Недоступна")
            
        except Exception as e:
            logger.error(f"Ошибка при сохранении статистики: {e}")
    
    def get_system_stats(self) -> dict:
        """Получить полную статистику системы"""
        try:
            return {
                "health": health_checker.get_health_summary(),
                "monitoring": monitoring_middleware.get_stats(),
                "processing": self.processing_service.get_reliability_stats(),
                "llm": self.llm_service.get_reliability_stats()
            }
        except Exception as e:
            logger.error(f"Ошибка при получении статистики: {e}")
            return {"error": str(e)}
    
    async def get_status_report(self) -> str:
        """Получить отчет о состоянии системы"""
        try:
            stats = self.get_system_stats()
            
            # Формируем отчет
            report = ["📊 **Отчет о состоянии системы**\n"]
            
            # Общее здоровье
            health = stats.get("health", {})
            overall_status = health.get("overall_status", "unknown")
            status_emoji = {
                "healthy": "✅",
                "degraded": "⚠️", 
                "unhealthy": "❌",
                "unknown": "❓"
            }.get(overall_status, "❓")
            
            report.append(f"**Общий статус:** {status_emoji} {overall_status}")
            
            # Мониторинг
            monitoring = stats.get("monitoring", {})
            report.append(f"**Всего запросов:** {monitoring.get('total_requests', 0)}")
            report.append(f"**Процент ошибок:** {monitoring.get('error_rate', 0):.1f}%")
            report.append(f"**Среднее время:** {monitoring.get('average_processing_time', 0):.3f}с")
            
            # Компоненты
            components = health.get("components", {})
            unhealthy_components = [
                name for name, comp in components.items() 
                if comp.get("status") == "unhealthy"
            ]
            
            if unhealthy_components:
                report.append(f"**Проблемные компоненты:** {', '.join(unhealthy_components)}")
            
            return "\n".join(report)
            
        except Exception as e:
            logger.error(f"Ошибка при формировании отчета: {e}")
            return f"❌ Ошибка при формировании отчета: {e}"


async def main_enhanced():
    """Главная функция для улучшенного бота"""
    bot = EnhancedTelegramBot()
    try:
        await bot.start()
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
    finally:
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main_enhanced())
