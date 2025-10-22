"""
Менеджер очереди задач для обработки протоколов
"""

import asyncio
import os
import psutil
from typing import Dict, List, Optional
from uuid import uuid4
from datetime import datetime
from loguru import logger

from src.models.task_queue import QueuedTask, TaskStatus, TaskPriority
from src.models.processing import ProcessingRequest
from database import db
from config import settings

try:
    from src.performance.oom_protection import get_oom_protection
    OOM_PROTECTION_AVAILABLE = True
except ImportError:
    OOM_PROTECTION_AVAILABLE = False
    logger.warning("OOM Protection недоступна для TaskQueueManager")


class TaskQueueManager:
    """Менеджер глобальной очереди задач с контролем ресурсов"""
    
    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=settings.max_queue_size)
        self.tasks: Dict[str, QueuedTask] = {}  # task_id -> QueuedTask
        self.active_tasks: Dict[str, asyncio.Task] = {}  # task_id -> asyncio.Task
        self.workers: List[asyncio.Task] = []
        self.is_running = False
        self._lock = asyncio.Lock()
        self.bot = None  # Будет инициализирован при старте воркеров
        
        # Определяем максимальное количество параллельных задач
        if settings.max_concurrent_tasks:
            self.max_concurrent = settings.max_concurrent_tasks
        else:
            # Автоматический расчет на основе ресурсов
            cpu_count = os.cpu_count() or 2
            available_memory_gb = psutil.virtual_memory().available / (1024**3)
            
            # Консервативный подход: 1 задача на 2GB RAM и 2 CPU ядра
            memory_limit = max(1, int(available_memory_gb / 2))
            cpu_limit = max(1, cpu_count // 2)
            
            self.max_concurrent = min(memory_limit, cpu_limit)
            logger.info(f"Автоматически установлено max_concurrent_tasks: {self.max_concurrent} "
                       f"(CPU: {cpu_count}, RAM: {available_memory_gb:.1f}GB)")
        
        # OOM Protection
        if OOM_PROTECTION_AVAILABLE:
            self.oom_protection = get_oom_protection()
        else:
            self.oom_protection = None
        
        # Фоновая задача очистки
        self.cleanup_task: Optional[asyncio.Task] = None
    
    async def start_workers(self, num_workers: Optional[int] = None):
        """Запустить воркеры для обработки очереди"""
        if self.is_running:
            logger.warning("Воркеры уже запущены")
            return
        
        self.is_running = True
        num_workers = num_workers or self.max_concurrent
        
        logger.info(f"Запуск {num_workers} воркеров очереди задач...")
        
        # Инициализируем бота для воркеров
        from aiogram import Bot
        self.bot = Bot(token=settings.telegram_token)
        logger.info("Бот для очереди задач инициализирован")
        
        # Восстанавливаем задачи из БД
        await self._restore_queue_from_db()
        
        # Запускаем воркеры
        for i in range(num_workers):
            worker = asyncio.create_task(self._worker(i))
            self.workers.append(worker)
        
        # Запускаем фоновую задачу очистки
        self.cleanup_task = asyncio.create_task(self._cleanup_loop())
        
        logger.info(f"✅ {num_workers} воркеров запущены")
    
    async def stop_workers(self):
        """Остановить воркеры"""
        if not self.is_running:
            return
        
        logger.info("Остановка воркеров очереди задач...")
        self.is_running = False
        
        # Останавливаем задачу очистки
        if self.cleanup_task:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass
        
        # Отменяем активные задачи
        for task in self.active_tasks.values():
            task.cancel()
        
        # Останавливаем воркеры
        for worker in self.workers:
            worker.cancel()
        
        # Ждем завершения
        await asyncio.gather(*self.workers, return_exceptions=True)
        
        self.workers.clear()
        self.active_tasks.clear()
        
        # Закрываем сессию бота
        if self.bot and self.bot.session:
            await self.bot.session.close()
            logger.info("Сессия бота для очереди задач закрыта")
        
        self.bot = None
        logger.info("✅ Воркеры остановлены")
    
    async def add_task(self, request: ProcessingRequest, chat_id: int, 
                      priority: TaskPriority = TaskPriority.NORMAL) -> QueuedTask:
        """Добавить задачу в очередь"""
        task_id = uuid4()
        
        task = QueuedTask(
            task_id=task_id,
            user_id=request.user_id,
            chat_id=chat_id,
            request=request,
            priority=priority,
            created_at=datetime.now()
        )
        
        async with self._lock:
            # Сохраняем в память
            self.tasks[str(task_id)] = task
            
            # Сохраняем в БД
            await self._save_task_to_db(task)
            
            # Добавляем в очередь
            await self.queue.put(task)
            
            logger.info(f"Задача {task_id} добавлена в очередь (приоритет: {priority.name})")
        
        return task
    
    async def cancel_task(self, task_id: str) -> bool:
        """Отменить задачу"""
        async with self._lock:
            if task_id not in self.tasks:
                logger.warning(f"Задача {task_id} не найдена")
                return False
            
            task = self.tasks[task_id]
            
            # Если задача уже обрабатывается, отменяем asyncio.Task
            if task_id in self.active_tasks:
                active_task = self.active_tasks[task_id]
                active_task.cancel()
                logger.info(f"Активная задача {task_id} отменена")
            
            # Обновляем статус
            task.status = TaskStatus.CANCELLED
            await self._update_task_status(task_id, TaskStatus.CANCELLED)
            
            # Удаляем из памяти
            del self.tasks[task_id]
            
            logger.info(f"Задача {task_id} отменена")
            return True
    
    async def get_task(self, task_id: str) -> Optional[QueuedTask]:
        """Получить задачу по ID"""
        return self.tasks.get(task_id)
    
    async def get_queue_position(self, task_id: str) -> Optional[int]:
        """Получить позицию задачи в очереди"""
        async with self._lock:
            if task_id not in self.tasks:
                return None
            
            task = self.tasks[task_id]
            
            if task.status != TaskStatus.QUEUED:
                return None
            
            # Считаем позицию на основе задач с таким же или более высоким приоритетом
            position = 0
            for other_task in self.tasks.values():
                if other_task.status == TaskStatus.QUEUED:
                    # Проверяем приоритет и время создания
                    if (other_task.priority.value > task.priority.value or
                        (other_task.priority == task.priority and 
                         other_task.created_at < task.created_at)):
                        position += 1
            
            return position
    
    async def get_queue_size(self) -> int:
        """Получить количество задач в очереди"""
        async with self._lock:
            return sum(1 for t in self.tasks.values() if t.status == TaskStatus.QUEUED)
    
    async def _worker(self, worker_id: int):
        """Воркер для обработки задач из очереди"""
        logger.info(f"Воркер {worker_id} запущен")
        
        while self.is_running:
            try:
                # Получаем задачу из очереди
                task = await self.queue.get()
                
                # Проверяем, не была ли задача отменена
                if task.status == TaskStatus.CANCELLED:
                    self.queue.task_done()
                    continue
                
                # Проверяем доступность ресурсов
                if not await self._check_resources_available():
                    logger.warning(f"Воркер {worker_id}: недостаточно ресурсов, возвращаем задачу в очередь")
                    await self.queue.put(task)
                    await asyncio.sleep(5)  # Ждем освобождения ресурсов
                    self.queue.task_done()
                    continue
                
                # Обрабатываем задачу
                logger.info(f"Воркер {worker_id} начал обработку задачи {task.task_id}")
                
                # Обновляем статус
                task.status = TaskStatus.PROCESSING
                task.started_at = datetime.now()
                await self._update_task_status(str(task.task_id), TaskStatus.PROCESSING, 
                                             started_at=task.started_at.isoformat())
                
                # Создаем задачу обработки
                processing_task = asyncio.create_task(
                    self._process_task(task)
                )
                self.active_tasks[str(task.task_id)] = processing_task
                
                try:
                    await processing_task
                except asyncio.CancelledError:
                    logger.info(f"Задача {task.task_id} была отменена")
                    task.status = TaskStatus.CANCELLED
                    await self._update_task_status(str(task.task_id), TaskStatus.CANCELLED)
                except Exception as e:
                    logger.error(f"Ошибка при обработке задачи {task.task_id}: {e}")
                    task.status = TaskStatus.FAILED
                    task.error_message = str(e)
                    await self._update_task_status(str(task.task_id), TaskStatus.FAILED,
                                                  error_message=str(e))
                finally:
                    # Удаляем из активных задач
                    if str(task.task_id) in self.active_tasks:
                        del self.active_tasks[str(task.task_id)]
                    
                    # Удаляем из памяти
                    if str(task.task_id) in self.tasks:
                        del self.tasks[str(task.task_id)]
                    
                    self.queue.task_done()
                
            except asyncio.CancelledError:
                logger.info(f"Воркер {worker_id} получил сигнал остановки")
                break
            except Exception as e:
                logger.error(f"Ошибка в воркере {worker_id}: {e}")
                await asyncio.sleep(1)
        
        logger.info(f"Воркер {worker_id} остановлен")
    
    async def _process_task(self, task: QueuedTask):
        """Обработать задачу"""
        from src.services.optimized_processing_service import OptimizedProcessingService
        from src.ux.progress_tracker import ProgressFactory
        from src.ux.queue_tracker import QueuePositionTracker
        from config import settings as cfg
        
        try:
            # Небольшая задержка для гарантии, что message_id успел сохраниться
            await asyncio.sleep(0.1)
            
            # Получаем актуальный message_id из self.tasks (может быть обновлен после добавления в очередь)
            task_in_memory = self.tasks.get(str(task.task_id))
            message_id_to_delete = task_in_memory.message_id if task_in_memory else task.message_id
            
            # Удаляем старое сообщение об очереди перед созданием нового ProgressTracker
            if message_id_to_delete:
                try:
                    await self.bot.delete_message(chat_id=task.chat_id, message_id=message_id_to_delete)
                    logger.debug(f"Удалено сообщение очереди {message_id_to_delete} для задачи {task.task_id}")
                except Exception as e:
                    logger.warning(f"Не удалось удалить сообщение очереди: {e}")
            
            # Создаем progress tracker
            progress_tracker = await ProgressFactory.create_file_processing_tracker(
                self.bot, task.chat_id, cfg.enable_diarization
            )
            
            # Обрабатываем файл
            processing_service = OptimizedProcessingService()
            result = await processing_service.process_file(task.request, progress_tracker)
            
            # Отправляем результат пользователю
            await self._send_result_to_user(self.bot, task, result)
            
            # Обновляем статус
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now()
            await self._update_task_status(str(task.task_id), TaskStatus.COMPLETED)
            
            logger.info(f"Задача {task.task_id} успешно выполнена")
            
        except Exception as e:
            logger.error(f"Ошибка обработки задачи {task.task_id}: {e}")
            raise
    
    async def _send_result_to_user(self, bot, task: QueuedTask, result):
        """Отправить результат обработки пользователю"""
        from src.ux.message_builder import MessageBuilder
        from aiogram.types import FSInputFile
        import tempfile
        import os
        
        try:
            # Получаем настройки вывода пользователя
            from src.services.user_service import UserService
            user_service = UserService()
            user = await user_service.get_user_by_telegram_id(task.user_id)
            output_mode = getattr(user, 'protocol_output_mode', None) or 'messages'
            
            # Формируем словарь с результатом для MessageBuilder
            result_dict = {
                "template_used": result.template_used if hasattr(result, 'template_used') else {"name": "Неизвестный"},
                "llm_provider_used": result.llm_provider_used,
                "llm_model_name": result.llm_provider_used,
                "transcription_result": {
                    "transcription": result.transcription_result.transcription if result.transcription_result else "",
                    "diarization": result.transcription_result.diarization if result.transcription_result else None,
                    "compression_info": result.transcription_result.compression_info if result.transcription_result else None
                },
                "processing_duration": result.processing_duration if hasattr(result, 'processing_duration') else None
            }
            
            # Формируем сообщение с результатом
            result_message = MessageBuilder.processing_complete_message(result_dict)
            
            await bot.send_message(
                chat_id=task.chat_id,
                text=result_message,
                parse_mode="Markdown"
            )
            
            # Отправляем протокол
            if not result.protocol_text:
                logger.warning("protocol_text пустой или None")
                await bot.send_message(
                    chat_id=task.chat_id,
                    text="❌ Протокол не был сгенерирован"
                )
            else:
                if output_mode in ('file', 'pdf'):
                    # Отправляем как файл
                    suffix = '.pdf' if output_mode == 'pdf' else '.md'
                    safe_name = os.path.splitext(os.path.basename(task.request.file_name))[0][:40] or 'protocol'
                    
                    with tempfile.NamedTemporaryFile(mode='w', suffix=suffix, delete=False, encoding='utf-8') as f:
                        temp_path = f.name
                        
                        if output_mode == 'pdf':
                            # Конвертируем в PDF
                            try:
                                import markdown
                                from weasyprint import HTML
                                html_content = markdown.markdown(result.protocol_text)
                                HTML(string=html_content).write_pdf(temp_path)
                            except Exception as e:
                                logger.error(f"Ошибка конвертации в PDF: {e}")
                                f.write(result.protocol_text)
                        else:
                            f.write(result.protocol_text)
                    
                    try:
                        input_file = FSInputFile(temp_path, filename=f"{safe_name}{suffix}")
                        await bot.send_document(
                            chat_id=task.chat_id,
                            document=input_file,
                            caption="📄 Протокол готов!"
                        )
                    finally:
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                else:
                    # Отправляем как сообщения (разбиваем если нужно)
                    protocol_text = result.protocol_text
                    max_length = 4000
                    
                    if len(protocol_text) <= max_length:
                        await bot.send_message(
                            chat_id=task.chat_id,
                            text=protocol_text,
                            parse_mode="Markdown"
                        )
                    else:
                        # Разбиваем на части
                        parts = []
                        current_part = ""
                        
                        for line in protocol_text.split('\n'):
                            if len(current_part) + len(line) + 1 <= max_length:
                                current_part += line + '\n'
                            else:
                                if current_part:
                                    parts.append(current_part.strip())
                                current_part = line + '\n'
                        
                        if current_part:
                            parts.append(current_part.strip())
                        
                        # Отправляем части
                        for i, part in enumerate(parts):
                            header = f"📄 **Протокол встречи** (часть {i+1}/{len(parts)})\n\n"
                            await bot.send_message(
                                chat_id=task.chat_id,
                                text=header + part,
                                parse_mode="Markdown"
                            )
            
        except Exception as e:
            logger.error(f"Ошибка отправки результата: {e}")
            await bot.send_message(
                chat_id=task.chat_id,
                text=f"❌ Ошибка при отправке результата: {str(e)}"
            )
    
    async def _check_resources_available(self) -> bool:
        """Проверить доступность ресурсов для обработки"""
        if not self.oom_protection:
            return True
        
        try:
            memory_status = self.oom_protection.get_memory_status()
            status_level = memory_status.get('status', 'ok')
            
            if status_level == 'critical':
                logger.warning("Критический уровень памяти - откладываем обработку")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Ошибка проверки ресурсов: {e}")
            return True  # В случае ошибки разрешаем обработку
    
    async def _save_task_to_db(self, task: QueuedTask):
        """Сохранить задачу в БД"""
        try:
            task_data = task.to_dict()
            await db.save_queue_task(task_data)
        except Exception as e:
            logger.error(f"Ошибка сохранения задачи в БД: {e}")
    
    async def _update_task_status(self, task_id: str, status: TaskStatus, 
                                started_at: Optional[str] = None,
                                error_message: Optional[str] = None):
        """Обновить статус задачи в БД"""
        try:
            await db.update_queue_task_status(
                task_id, status.value, started_at, error_message
            )
        except Exception as e:
            logger.error(f"Ошибка обновления статуса задачи: {e}")
    
    async def _restore_queue_from_db(self):
        """Восстановить очередь задач из БД при запуске"""
        try:
            pending_tasks = await db.get_pending_queue_tasks()
            
            if not pending_tasks:
                logger.info("Нет задач для восстановления из БД")
                return
            
            logger.info(f"Восстановление {len(pending_tasks)} задач из БД...")
            
            for task_data in pending_tasks:
                try:
                    task = QueuedTask.from_db_row(task_data)
                    self.tasks[str(task.task_id)] = task
                    await self.queue.put(task)
                    logger.info(f"Задача {task.task_id} восстановлена из БД")
                except Exception as e:
                    logger.error(f"Ошибка восстановления задачи: {e}")
            
            logger.info(f"✅ Восстановлено {len(pending_tasks)} задач")
            
        except Exception as e:
            logger.error(f"Ошибка восстановления очереди из БД: {e}")
    
    async def _cleanup_loop(self):
        """Периодическая очистка завершенных задач"""
        while self.is_running:
            try:
                await asyncio.sleep(settings.queue_cleanup_interval_hours * 3600)
                
                logger.info("Запуск очистки завершенных задач...")
                deleted = await db.cleanup_completed_queue_tasks(
                    hours=settings.queue_cleanup_interval_hours
                )
                
                if deleted > 0:
                    logger.info(f"Удалено {deleted} завершенных задач из БД")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка в цикле очистки: {e}")


# Глобальный экземпляр менеджера очереди
task_queue_manager = TaskQueueManager()

