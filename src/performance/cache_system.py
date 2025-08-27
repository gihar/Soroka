"""
Система кэширования для оптимизации производительности
"""

import hashlib
import json
import pickle
import asyncio
import aiofiles
from typing import Any, Optional, Dict, Union, List
from datetime import datetime, timedelta
from pathlib import Path
from loguru import logger
from dataclasses import dataclass, asdict


@dataclass
class CacheEntry:
    """Запись в кэше"""
    key: str
    value: Any
    created_at: datetime
    expires_at: Optional[datetime] = None
    access_count: int = 0
    last_accessed: datetime = None
    size_bytes: int = 0
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.last_accessed is None:
            self.last_accessed = self.created_at
        if self.metadata is None:
            self.metadata = {}


class PerformanceCache:
    """Высокопроизводительная система кэширования"""
    
    def __init__(self, cache_dir: str = "cache", max_memory_mb: int = 512):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        
        # Настройки кэша
        self.max_memory_bytes = max_memory_mb * 1024 * 1024
        self.current_memory_usage = 0
        
        # Кэш в памяти для быстрого доступа
        self.memory_cache: Dict[str, CacheEntry] = {}
        
        # Кэш на диске для больших объектов
        self.disk_cache_dir = self.cache_dir / "disk"
        self.disk_cache_dir.mkdir(exist_ok=True)
        
        # Статистика
        self.stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "disk_reads": 0,
            "disk_writes": 0
        }
        
        # Время жизни кэша по типам
        self.default_ttl = {
            "transcription": timedelta(hours=24),
            "llm_response": timedelta(hours=6),
            "file_info": timedelta(hours=1),
            "user_data": timedelta(minutes=30),
            "template": timedelta(hours=12),
            "diarization": timedelta(hours=24)
        }
    
    def _generate_key(self, prefix: str, data: Union[str, Dict, List]) -> str:
        """Генерировать ключ кэша"""
        if isinstance(data, (dict, list)):
            data_str = json.dumps(data, sort_keys=True)
        else:
            data_str = str(data)
        
        hash_obj = hashlib.sha256(data_str.encode())
        return f"{prefix}:{hash_obj.hexdigest()[:16]}"
    
    def _calculate_size(self, value: Any) -> int:
        """Подсчитать размер объекта в байтах"""
        try:
            return len(pickle.dumps(value))
        except Exception:
            # Fallback для объектов, которые нельзя сериализовать
            return len(str(value).encode())
    
    def _should_cache_to_disk(self, size_bytes: int) -> bool:
        """Определить, нужно ли кэшировать на диск"""
        # Объекты больше 1MB кэшируем на диск
        return size_bytes > 1024 * 1024
    
    async def get(self, key: str) -> Optional[Any]:
        """Получить значение из кэша"""
        # Сначала проверяем кэш в памяти
        if key in self.memory_cache:
            entry = self.memory_cache[key]
            
            # Проверяем срок действия
            if entry.expires_at and datetime.now() > entry.expires_at:
                await self.delete(key)
                self.stats["misses"] += 1
                return None
            
            # Обновляем статистику доступа
            entry.access_count += 1
            entry.last_accessed = datetime.now()
            
            self.stats["hits"] += 1
            logger.debug(f"Cache hit (memory): {key}")
            return entry.value
        
        # Проверяем кэш на диске
        disk_path = self.disk_cache_dir / f"{key}.pkl"
        if disk_path.exists():
            try:
                async with aiofiles.open(disk_path, 'rb') as f:
                    content = await f.read()
                    entry = pickle.loads(content)
                
                # Проверяем срок действия
                if entry.expires_at and datetime.now() > entry.expires_at:
                    await aiofiles.os.remove(disk_path)
                    self.stats["misses"] += 1
                    return None
                
                # Обновляем статистику
                entry.access_count += 1
                entry.last_accessed = datetime.now()
                
                # Загружаем в память если размер позволяет
                if not self._should_cache_to_disk(entry.size_bytes):
                    await self._ensure_memory_capacity(entry.size_bytes)
                    self.memory_cache[key] = entry
                    self.current_memory_usage += entry.size_bytes
                
                self.stats["hits"] += 1
                self.stats["disk_reads"] += 1
                logger.debug(f"Cache hit (disk): {key}")
                return entry.value
                
            except Exception as e:
                logger.error(f"Ошибка чтения из дискового кэша {key}: {e}")
                # Удаляем поврежденный файл
                try:
                    await aiofiles.os.remove(disk_path)
                except:
                    pass
        
        self.stats["misses"] += 1
        logger.debug(f"Cache miss: {key}")
        return None
    
    async def set(self, key: str, value: Any, ttl: Optional[timedelta] = None, 
                  cache_type: str = "default") -> bool:
        """Сохранить значение в кэш"""
        try:
            size_bytes = self._calculate_size(value)
            created_at = datetime.now()
            
            # Определяем время жизни
            if ttl is None:
                ttl = self.default_ttl.get(cache_type, timedelta(hours=1))
            
            expires_at = created_at + ttl if ttl else None
            
            # Создаем запись
            entry = CacheEntry(
                key=key,
                value=value,
                created_at=created_at,
                expires_at=expires_at,
                size_bytes=size_bytes,
                metadata={"cache_type": cache_type}
            )
            
            # Определяем, куда кэшировать
            if self._should_cache_to_disk(size_bytes):
                # Кэшируем на диск
                await self._save_to_disk(key, entry)
                self.stats["disk_writes"] += 1
                logger.debug(f"Cached to disk: {key} ({size_bytes} bytes)")
            else:
                # Кэшируем в память
                await self._ensure_memory_capacity(size_bytes)
                self.memory_cache[key] = entry
                self.current_memory_usage += size_bytes
                logger.debug(f"Cached to memory: {key} ({size_bytes} bytes)")
            
            return True
            
        except Exception as e:
            logger.error(f"Ошибка сохранения в кэш {key}: {e}")
            return False
    
    async def _save_to_disk(self, key: str, entry: CacheEntry):
        """Сохранить запись на диск"""
        disk_path = self.disk_cache_dir / f"{key}.pkl"
        async with aiofiles.open(disk_path, 'wb') as f:
            content = pickle.dumps(entry)
            await f.write(content)
    
    async def _ensure_memory_capacity(self, required_bytes: int):
        """Обеспечить место в кэше памяти"""
        if self.current_memory_usage + required_bytes <= self.max_memory_bytes:
            return
        
        # Нужно освободить место - используем LRU
        entries_by_access = sorted(
            self.memory_cache.items(),
            key=lambda x: x[1].last_accessed
        )
        
        for key, entry in entries_by_access:
            await self.delete(key)
            self.stats["evictions"] += 1
            
            if self.current_memory_usage + required_bytes <= self.max_memory_bytes:
                break
    
    async def delete(self, key: str) -> bool:
        """Удалить запись из кэша"""
        deleted = False
        
        # Удаляем из памяти
        if key in self.memory_cache:
            entry = self.memory_cache[key]
            self.current_memory_usage -= entry.size_bytes
            del self.memory_cache[key]
            deleted = True
        
        # Удаляем с диска
        disk_path = self.disk_cache_dir / f"{key}.pkl"
        if disk_path.exists():
            try:
                await aiofiles.os.remove(disk_path)
                deleted = True
            except Exception as e:
                logger.error(f"Ошибка удаления файла кэша {disk_path}: {e}")
        
        return deleted
    
    async def clear(self, cache_type: Optional[str] = None):
        """Очистить кэш"""
        if cache_type is None:
            # Очищаем весь кэш
            self.memory_cache.clear()
            self.current_memory_usage = 0
            
            # Очищаем диск
            for cache_file in self.disk_cache_dir.glob("*.pkl"):
                try:
                    await aiofiles.os.remove(cache_file)
                except Exception as e:
                    logger.error(f"Ошибка удаления файла кэша {cache_file}: {e}")
        else:
            # Очищаем кэш определенного типа
            to_delete = []
            for key, entry in self.memory_cache.items():
                if entry.metadata.get("cache_type") == cache_type:
                    to_delete.append(key)
            
            for key in to_delete:
                await self.delete(key)
    
    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику кэша"""
        total_requests = self.stats["hits"] + self.stats["misses"]
        hit_rate = (self.stats["hits"] / total_requests * 100) if total_requests > 0 else 0
        
        return {
            **self.stats,
            "hit_rate_percent": round(hit_rate, 2),
            "memory_usage_mb": round(self.current_memory_usage / (1024 * 1024), 2),
            "memory_usage_percent": round(
                (self.current_memory_usage / self.max_memory_bytes) * 100, 2
            ),
            "memory_entries": len(self.memory_cache),
            "disk_entries": len(list(self.disk_cache_dir.glob("*.pkl")))
        }
    
    async def cleanup_expired(self):
        """Очистить просроченные записи"""
        now = datetime.now()
        expired_keys = []
        
        # Проверяем память
        for key, entry in self.memory_cache.items():
            if entry.expires_at and now > entry.expires_at:
                expired_keys.append(key)
        
        for key in expired_keys:
            await self.delete(key)
        
        # Проверяем диск
        for cache_file in self.disk_cache_dir.glob("*.pkl"):
            try:
                async with aiofiles.open(cache_file, 'rb') as f:
                    content = await f.read()
                    entry = pickle.loads(content)
                
                if entry.expires_at and now > entry.expires_at:
                    await aiofiles.os.remove(cache_file)
                    
            except Exception as e:
                logger.error(f"Ошибка при проверке срока действия {cache_file}: {e}")
                # Удаляем поврежденный файл
                try:
                    await aiofiles.os.remove(cache_file)
                except:
                    pass


# Глобальный экземпляр кэша
performance_cache = PerformanceCache()


class CacheDecorator:
    """Декоратор для автоматического кэширования функций"""
    
    def __init__(self, cache_type: str = "default", ttl: Optional[timedelta] = None):
        self.cache_type = cache_type
        self.ttl = ttl
    
    def __call__(self, func):
        async def wrapper(*args, **kwargs):
            # Генерируем ключ кэша на основе функции и аргументов
            # Исключаем self из аргументов для избежания ошибок сериализации
            cache_args = []
            cache_kwargs = {}
            
            # Пропускаем первый аргумент (self) если это метод класса
            for i, arg in enumerate(args):
                if i == 0 and hasattr(arg, '__class__'):
                    # Пропускаем self, но можем добавить его идентификатор
                    cache_args.append(arg.__class__.__name__)
                else:
                    # Проверяем, можно ли сериализовать аргумент
                    try:
                        import json
                        json.dumps(arg)
                        cache_args.append(arg)
                    except (TypeError, ValueError):
                        # Если не можем сериализовать, используем строковое представление
                        cache_args.append(str(arg))
            
            # Аналогично для kwargs
            for key, value in kwargs.items():
                try:
                    import json
                    json.dumps(value)
                    cache_kwargs[key] = value
                except (TypeError, ValueError):
                    cache_kwargs[key] = str(value)
            
            cache_key = performance_cache._generate_key(
                f"func:{func.__name__}",
                {"args": cache_args, "kwargs": cache_kwargs}
            )
            
            # Проверяем кэш
            cached_result = await performance_cache.get(cache_key)
            if cached_result is not None:
                return cached_result
            
            # Выполняем функцию и кэшируем результат
            result = await func(*args, **kwargs)
            await performance_cache.set(cache_key, result, self.ttl, self.cache_type)
            
            return result
        
        return wrapper


# Удобные декораторы
def cache_transcription(ttl: Optional[timedelta] = None):
    return CacheDecorator("transcription", ttl)

def cache_llm_response(ttl: Optional[timedelta] = None):
    return CacheDecorator("llm_response", ttl)

def cache_diarization(ttl: Optional[timedelta] = None):
    return CacheDecorator("diarization", ttl)
