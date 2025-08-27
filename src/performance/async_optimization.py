"""
Оптимизация асинхронных операций и управление ресурсами
"""

import asyncio
import aiohttp
import aiofiles
import os
import ssl
from typing import Any, Callable, List, Optional, Dict, Union
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import time
from loguru import logger
from dataclasses import dataclass
from contextlib import asynccontextmanager


@dataclass
class TaskResult:
    """Результат выполнения задачи"""
    task_id: str
    success: bool
    result: Any = None
    error: Optional[Exception] = None
    duration: float = 0.0


class AsyncTaskPool:
    """Пул асинхронных задач с ограничением конкурентности"""
    
    def __init__(self, max_concurrent: int = 10, timeout: float = 300.0):
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self.completed_tasks: List[TaskResult] = []
    
    async def submit_task(self, task_id: str, coro_func: Callable, *args, **kwargs) -> TaskResult:
        """Добавить задачу в пул"""
        async with self.semaphore:
            start_time = time.time()
            
            try:
                # Создаем и запускаем задачу
                task = asyncio.create_task(coro_func(*args, **kwargs))
                self.active_tasks[task_id] = task
                
                # Ждем выполнения с таймаутом
                result = await asyncio.wait_for(task, timeout=self.timeout)
                
                duration = time.time() - start_time
                task_result = TaskResult(
                    task_id=task_id,
                    success=True,
                    result=result,
                    duration=duration
                )
                
                logger.debug(f"Задача {task_id} выполнена за {duration:.2f}с")
                
            except asyncio.TimeoutError:
                duration = time.time() - start_time
                task_result = TaskResult(
                    task_id=task_id,
                    success=False,
                    error=TimeoutError(f"Задача {task_id} превысила таймаут {self.timeout}с"),
                    duration=duration
                )
                logger.warning(f"Задача {task_id} превысила таймаут {self.timeout}с")
                
            except Exception as e:
                duration = time.time() - start_time
                task_result = TaskResult(
                    task_id=task_id,
                    success=False,
                    error=e,
                    duration=duration
                )
                logger.error(f"Ошибка в задаче {task_id}: {e}")
                
            finally:
                # Убираем из активных задач
                if task_id in self.active_tasks:
                    del self.active_tasks[task_id]
                
                self.completed_tasks.append(task_result)
                
                # Ограничиваем историю
                if len(self.completed_tasks) > 1000:
                    self.completed_tasks = self.completed_tasks[-500:]
            
            return task_result
    
    async def submit_batch(self, tasks: List[tuple]) -> List[TaskResult]:
        """Выполнить пакет задач параллельно"""
        batch_tasks = []
        
        for i, (coro_func, args, kwargs) in enumerate(tasks):
            task_id = f"batch_{int(time.time())}_{i}"
            task = self.submit_task(task_id, coro_func, *args, kwargs or {})
            batch_tasks.append(task)
        
        return await asyncio.gather(*batch_tasks, return_exceptions=True)
    
    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику пула задач"""
        recent_tasks = [t for t in self.completed_tasks 
                       if time.time() - t.duration < 3600]  # За последний час
        
        successful = [t for t in recent_tasks if t.success]
        failed = [t for t in recent_tasks if not t.success]
        
        return {
            "active_tasks": len(self.active_tasks),
            "max_concurrent": self.max_concurrent,
            "completed_last_hour": len(recent_tasks),
            "success_rate": len(successful) / len(recent_tasks) * 100 if recent_tasks else 0,
            "avg_duration": sum(t.duration for t in successful) / len(successful) if successful else 0,
            "active_task_ids": list(self.active_tasks.keys())
        }


class OptimizedHTTPClient:
    """Оптимизированный HTTP клиент с пулом соединений"""
    
    def __init__(self, max_connections: int = 100, timeout: float = 30.0, verify_ssl: bool = True):
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.max_connections = max_connections
        self.verify_ssl = verify_ssl
        self.connector: Optional[aiohttp.TCPConnector] = None
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        # Создаем SSL контекст
        if self.verify_ssl:
            ssl_context = ssl.create_default_context()
        else:
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        
        # Создаем connector с SSL контекстом
        self.connector = aiohttp.TCPConnector(
            limit=self.max_connections,
            limit_per_host=20,
            ttl_dns_cache=300,
            use_dns_cache=True,
            ssl=ssl_context
        )
        
        self.session = aiohttp.ClientSession(
            connector=self.connector,
            timeout=self.timeout
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
        if self.connector:
            await self.connector.close()
    
    async def download_file(self, url: str, file_path: str, 
                          chunk_size: int = 8192) -> Dict[str, Any]:
        """Оптимизированное скачивание файла"""
        if not self.session:
            raise RuntimeError("HTTP клиент не инициализирован")
        
        start_time = time.time()
        bytes_downloaded = 0
        
        try:
            async with self.session.get(url) as response:
                response.raise_for_status()
                
                # Получаем размер файла если доступен
                content_length = response.headers.get('content-length')
                total_size = int(content_length) if content_length else None
                
                async with aiofiles.open(file_path, 'wb') as file:
                    async for chunk in response.content.iter_chunked(chunk_size):
                        await file.write(chunk)
                        bytes_downloaded += len(chunk)
                
                duration = time.time() - start_time
                speed_mbps = (bytes_downloaded / (1024 * 1024)) / duration if duration > 0 else 0
                
                return {
                    "success": True,
                    "bytes_downloaded": bytes_downloaded,
                    "duration": duration,
                    "speed_mbps": speed_mbps,
                    "file_path": file_path
                }
                
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"Ошибка скачивания {url}: {e}")
            
            return {
                "success": False,
                "error": str(e),
                "bytes_downloaded": bytes_downloaded,
                "duration": duration
            }


class ThreadPoolManager:
    """Менеджер пулов потоков для CPU-интенсивных задач"""
    
    def __init__(self, max_workers: int = None):
        self.max_workers = max_workers or min(32, (os.cpu_count() or 1) + 4)
        self.thread_pool = ThreadPoolExecutor(max_workers=self.max_workers)
        self.process_pool = ProcessPoolExecutor(max_workers=max(1, (os.cpu_count() or 1) // 2))
    
    async def run_in_thread(self, func: Callable, *args, **kwargs) -> Any:
        """Выполнить функцию в отдельном потоке"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.thread_pool, func, *args, **kwargs)
    
    async def run_in_process(self, func: Callable, *args, **kwargs) -> Any:
        """Выполнить функцию в отдельном процессе"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.process_pool, func, *args, **kwargs)
    
    def shutdown(self):
        """Закрыть пулы"""
        self.thread_pool.shutdown(wait=True)
        self.process_pool.shutdown(wait=True)


class BatchProcessor:
    """Пакетная обработка для оптимизации производительности"""
    
    def __init__(self, batch_size: int = 10, flush_interval: float = 5.0):
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.pending_items: List[Any] = []
        self.last_flush = time.time()
        self.processor_func: Optional[Callable] = None
    
    def set_processor(self, func: Callable):
        """Установить функцию обработки пакета"""
        self.processor_func = func
    
    async def add_item(self, item: Any) -> bool:
        """Добавить элемент в пакет"""
        self.pending_items.append(item)
        
        # Проверяем условия для флуша
        should_flush = (
            len(self.pending_items) >= self.batch_size or
            time.time() - self.last_flush >= self.flush_interval
        )
        
        if should_flush:
            await self.flush()
            return True
        
        return False
    
    async def flush(self):
        """Обработать накопленный пакет"""
        if not self.pending_items or not self.processor_func:
            return
        
        items_to_process = self.pending_items.copy()
        self.pending_items.clear()
        self.last_flush = time.time()
        
        try:
            await self.processor_func(items_to_process)
            logger.debug(f"Обработан пакет из {len(items_to_process)} элементов")
        except Exception as e:
            logger.error(f"Ошибка обработки пакета: {e}")
            # Возвращаем элементы обратно для повторной попытки
            self.pending_items.extend(items_to_process)


class AsyncResourceManager:
    """Менеджер асинхронных ресурсов"""
    
    def __init__(self):
        self.resources: Dict[str, Any] = {}
        self.cleanup_tasks: Dict[str, asyncio.Task] = {}
    
    async def acquire_resource(self, resource_id: str, 
                             factory_func: Callable, 
                             cleanup_func: Optional[Callable] = None,
                             ttl: float = 3600.0) -> Any:
        """Получить ресурс (создать если не существует)"""
        if resource_id in self.resources:
            return self.resources[resource_id]
        
        # Создаем ресурс
        resource = await factory_func()
        self.resources[resource_id] = resource
        
        # Планируем очистку
        if cleanup_func and ttl > 0:
            cleanup_task = asyncio.create_task(
                self._schedule_cleanup(resource_id, cleanup_func, ttl)
            )
            self.cleanup_tasks[resource_id] = cleanup_task
        
        logger.debug(f"Создан ресурс: {resource_id}")
        return resource
    
    async def release_resource(self, resource_id: str):
        """Освободить ресурс"""
        if resource_id in self.resources:
            del self.resources[resource_id]
        
        if resource_id in self.cleanup_tasks:
            self.cleanup_tasks[resource_id].cancel()
            del self.cleanup_tasks[resource_id]
        
        logger.debug(f"Освобожден ресурс: {resource_id}")
    
    async def _schedule_cleanup(self, resource_id: str, 
                              cleanup_func: Callable, ttl: float):
        """Запланированная очистка ресурса"""
        try:
            await asyncio.sleep(ttl)
            
            if resource_id in self.resources:
                resource = self.resources[resource_id]
                await cleanup_func(resource)
                await self.release_resource(resource_id)
                logger.debug(f"Автоматически очищен ресурс: {resource_id}")
                
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Ошибка очистки ресурса {resource_id}: {e}")


@asynccontextmanager
async def optimized_file_processing():
    """Контекстный менеджер для оптимизированной обработки файлов"""
    # Импортируем настройки SSL из конфигурации
    try:
        from config import settings
        verify_ssl = getattr(settings, 'ssl_verify', True)
    except:
        verify_ssl = True  # По умолчанию проверяем SSL
    
    http_client = OptimizedHTTPClient(verify_ssl=verify_ssl)
    thread_manager = ThreadPoolManager()
    resource_manager = AsyncResourceManager()
    
    try:
        async with http_client:
            yield {
                "http_client": http_client,
                "thread_manager": thread_manager,
                "resource_manager": resource_manager
            }
    finally:
        thread_manager.shutdown()


# Глобальные экземпляры
task_pool = AsyncTaskPool(max_concurrent=5)  # Консервативное значение для начала
thread_manager = ThreadPoolManager()


async def optimize_io_operations(operations: List[Callable]) -> List[Any]:
    """Оптимизированное выполнение I/O операций"""
    if not operations:
        return []
    
    # Разделяем на пакеты для контроля нагрузки
    batch_size = min(10, len(operations))
    results = []
    
    for i in range(0, len(operations), batch_size):
        batch = operations[i:i + batch_size]
        batch_tasks = [op() for op in batch]
        batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
        results.extend(batch_results)
        
        # Небольшая пауза между пакетами для снижения нагрузки
        if i + batch_size < len(operations):
            await asyncio.sleep(0.1)
    
    return results


def async_lru_cache(maxsize: int = 128, ttl: float = 3600.0):
    """Асинхронный LRU кэш с TTL"""
    cache = {}
    access_times = {}
    
    def decorator(func):
        async def wrapper(*args, **kwargs):
            # Создаем ключ кэша
            key = f"{func.__name__}:{hash((args, tuple(sorted(kwargs.items()))))}"
            
            # Проверяем кэш
            if key in cache:
                # Проверяем TTL
                if time.time() - access_times[key] < ttl:
                    access_times[key] = time.time()
                    return cache[key]
                else:
                    # Просрочен
                    del cache[key]
                    del access_times[key]
            
            # Выполняем функцию
            result = await func(*args, **kwargs)
            
            # Сохраняем в кэш
            if len(cache) >= maxsize:
                # Удаляем самый старый элемент
                oldest_key = min(access_times.keys(), key=access_times.get)
                del cache[oldest_key]
                del access_times[oldest_key]
            
            cache[key] = result
            access_times[key] = time.time()
            
            return result
        
        return wrapper
    
    return decorator
