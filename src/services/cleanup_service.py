"""
Сервис для периодической очистки временных файлов
"""

import os
import asyncio
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional
from loguru import logger

from config import settings


class CleanupService:
    """Сервис для автоматической очистки временных файлов"""
    
    def __init__(self):
        self.temp_dir = Path(settings.temp_dir)
        self.cache_dir = Path("cache")
        self.cleanup_interval = getattr(settings, 'cleanup_interval_minutes', 30)  # минут
        self.file_max_age_hours = getattr(settings, 'temp_file_max_age_hours', 2)  # часов
        self.cache_max_age_hours = getattr(settings, 'cache_max_age_hours', 24)   # часов
        self.is_running = False
        self._cleanup_task: Optional[asyncio.Task] = None
    
    async def start_cleanup(self):
        """Запустить периодическую очистку"""
        if self.is_running:
            logger.warning("Очистка уже запущена")
            return
        
        self.is_running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info(f"Запущена периодическая очистка файлов (интервал: {self.cleanup_interval} мин)")
    
    async def stop_cleanup(self):
        """Остановить периодическую очистку"""
        if not self.is_running:
            return
        
        self.is_running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Периодическая очистка остановлена")
    
    async def _cleanup_loop(self):
        """Основной цикл очистки"""
        while self.is_running:
            try:
                await self.cleanup_old_files()
                await asyncio.sleep(self.cleanup_interval * 60)  # конвертируем минуты в секунды
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка в цикле очистки: {e}")
                await asyncio.sleep(60)  # ждем минуту перед повтором при ошибке
    
    async def cleanup_old_files(self):
        """Очистить старые файлы"""
        logger.debug("Начинаем очистку старых файлов")
        
        # Очищаем временные файлы
        temp_cleaned = await self._cleanup_directory(
            self.temp_dir, 
            max_age_hours=self.file_max_age_hours,
            file_patterns=['*.mp3', '*.wav', '*.m4a', '*.ogg', '*.mp4', '*.avi', '*.mov', '*.mkv', '*.tmp']
        )
        
        # Очищаем кэш файлы
        cache_cleaned = await self._cleanup_directory(
            self.cache_dir,
            max_age_hours=self.cache_max_age_hours,
            file_patterns=['*.pkl', '*.cache', '*.tmp']
        )
        
        if temp_cleaned > 0 or cache_cleaned > 0:
            logger.info(f"Очищено файлов: {temp_cleaned} временных, {cache_cleaned} кэш")
        else:
            logger.debug("Старые файлы не найдены")
    
    async def _cleanup_directory(self, directory: Path, max_age_hours: int, file_patterns: List[str]) -> int:
        """Очистить файлы в директории старше указанного возраста"""
        if not directory.exists():
            return 0
        
        cleaned_count = 0
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
        
        for pattern in file_patterns:
            for file_path in directory.glob(pattern):
                try:
                    # Проверяем возраст файла
                    file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                    
                    if file_mtime < cutoff_time:
                        # Проверяем, что файл не используется
                        if await self._is_file_safe_to_delete(file_path):
                            file_path.unlink()
                            cleaned_count += 1
                            logger.debug(f"Удален старый файл: {file_path}")
                        else:
                            logger.debug(f"Файл используется, пропускаем: {file_path}")
                            
                except Exception as e:
                    logger.warning(f"Ошибка при удалении файла {file_path}: {e}")
        
        return cleaned_count
    
    async def _is_file_safe_to_delete(self, file_path: Path) -> bool:
        """Проверить, безопасно ли удалять файл"""
        try:
            # Проверяем, что файл не открыт другими процессами
            # В Unix-системах можно попробовать открыть файл в режиме записи
            with open(file_path, 'r+b') as f:
                pass
            return True
        except (PermissionError, OSError):
            # Файл используется другим процессом
            return False
        except Exception:
            # Другие ошибки - считаем безопасным для удаления
            return True
    
    async def force_cleanup_all(self):
        """Принудительная очистка всех временных файлов"""
        logger.info("Запущена принудительная очистка всех временных файлов")
        
        temp_cleaned = 0
        cache_cleaned = 0
        
        # Очищаем все временные файлы
        if self.temp_dir.exists():
            for file_path in self.temp_dir.iterdir():
                if file_path.is_file():
                    try:
                        file_path.unlink()
                        temp_cleaned += 1
                        logger.debug(f"Удален файл: {file_path}")
                    except Exception as e:
                        logger.warning(f"Ошибка при удалении {file_path}: {e}")
        
        # Очищаем кэш файлы
        if self.cache_dir.exists():
            for file_path in self.cache_dir.rglob("*"):
                if file_path.is_file() and file_path.suffix in ['.pkl', '.cache', '.tmp']:
                    try:
                        file_path.unlink()
                        cache_cleaned += 1
                        logger.debug(f"Удален кэш файл: {file_path}")
                    except Exception as e:
                        logger.warning(f"Ошибка при удалении кэш файла {file_path}: {e}")
        
        logger.info(f"Принудительная очистка завершена: {temp_cleaned} временных, {cache_cleaned} кэш файлов")
        return temp_cleaned + cache_cleaned
    
    def get_cleanup_stats(self) -> dict:
        """Получить статистику по файлам"""
        stats = {
            "temp_files": 0,
            "temp_size_mb": 0,
            "cache_files": 0,
            "cache_size_mb": 0,
            "old_temp_files": 0,
            "old_cache_files": 0
        }
        
        cutoff_time = datetime.now() - timedelta(hours=self.file_max_age_hours)
        
        # Анализируем временные файлы
        if self.temp_dir.exists():
            for file_path in self.temp_dir.iterdir():
                if file_path.is_file():
                    stats["temp_files"] += 1
                    stats["temp_size_mb"] += file_path.stat().st_size / (1024 * 1024)
                    
                    file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                    if file_mtime < cutoff_time:
                        stats["old_temp_files"] += 1
        
        # Анализируем кэш файлы
        if self.cache_dir.exists():
            for file_path in self.cache_dir.rglob("*"):
                if file_path.is_file() and file_path.suffix in ['.pkl', '.cache', '.tmp']:
                    stats["cache_files"] += 1
                    stats["cache_size_mb"] += file_path.stat().st_size / (1024 * 1024)
                    
                    file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                    if file_mtime < cutoff_time:
                        stats["old_cache_files"] += 1
        
        return stats


# Глобальный экземпляр сервиса очистки
cleanup_service = CleanupService()
