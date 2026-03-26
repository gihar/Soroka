"""
Система Fallback для graceful degradation
"""

import asyncio
from typing import Callable, Any, List, Optional, Dict
from dataclasses import dataclass
from enum import Enum
from loguru import logger


class FallbackStrategy(Enum):
    """Стратегии fallback"""
    FAIL_FAST = "fail_fast"              # Быстрый отказ
    RETRY_THEN_FALLBACK = "retry_fallback"  # Повтор, затем fallback
    GRACEFUL_DEGRADATION = "graceful"    # Graceful degradation
    CACHE_FALLBACK = "cache"             # Использование кеша


@dataclass
class FallbackOption:
    """Опция fallback"""
    name: str
    handler: Callable
    condition: Optional[Callable] = None  # Условие активации
    priority: int = 0                     # Приоритет (больше = выше)


class FallbackManager:
    """Менеджер fallback стратегий"""
    
    def __init__(self, name: str, strategy: FallbackStrategy = FallbackStrategy.GRACEFUL_DEGRADATION):
        self.name = name
        self.strategy = strategy
        self.primary_handler: Optional[Callable] = None
        self.fallback_options: List[FallbackOption] = []
        self.cache: Dict[str, Any] = {}
        self.stats = {
            "total_calls": 0,
            "primary_success": 0,
            "fallback_used": 0,
            "cache_used": 0,
            "failures": 0
        }
        # Информация о последнем выполнении (для корректных логов вызывающей стороны)
        self.last_execution: Dict[str, Any] = {
            "mode": None,            # primary | fallback | cache | error
            "fallback_name": None
        }
    
    def set_primary(self, handler: Callable):
        """Установить основной обработчик"""
        self.primary_handler = handler
        return self
    
    def add_fallback(self, name: str, handler: Callable, condition: Optional[Callable] = None, priority: int = 0):
        """Добавить fallback опцию"""
        fallback = FallbackOption(name, handler, condition, priority)
        self.fallback_options.append(fallback)
        # Сортируем по приоритету (больше = выше)
        self.fallback_options.sort(key=lambda x: x.priority, reverse=True)
        logger.info(f"Добавлен fallback '{name}' для '{self.name}' (приоритет: {priority})")
        return self
    
    def cache_result(self, key: str, result: Any, ttl: Optional[float] = None):
        """Кешировать результат"""
        cache_entry = {
            "result": result,
            "timestamp": asyncio.get_event_loop().time(),
            "ttl": ttl
        }
        self.cache[key] = cache_entry
        logger.debug(f"Результат закеширован для '{self.name}': {key}")
    
    def get_cached_result(self, key: str) -> Optional[Any]:
        """Получить результат из кеша"""
        if key not in self.cache:
            return None
        
        entry = self.cache[key]
        current_time = asyncio.get_event_loop().time()
        
        # Проверяем TTL
        if entry["ttl"] and (current_time - entry["timestamp"]) > entry["ttl"]:
            del self.cache[key]
            return None
        
        logger.debug(f"Результат получен из кеша для '{self.name}': {key}")
        return entry["result"]
    
    async def execute(self, *args, cache_key: Optional[str] = None, **kwargs) -> Any:
        """Выполнить с fallback логикой"""
        self.stats["total_calls"] += 1
        
        # Проверяем кеш если указан ключ
        if cache_key and self.strategy == FallbackStrategy.CACHE_FALLBACK:
            cached_result = self.get_cached_result(cache_key)
            if cached_result is not None:
                self.stats["cache_used"] += 1
                self.last_execution = {"mode": "cache", "fallback_name": "cache"}
                return cached_result
        
        # Пытаемся выполнить основной обработчик
        if self.primary_handler:
            try:
                logger.debug(f"Выполнение основного обработчика для '{self.name}'")
                
                if asyncio.iscoroutinefunction(self.primary_handler):
                    result = await self.primary_handler(*args, **kwargs)
                else:
                    result = self.primary_handler(*args, **kwargs)
                
                self.stats["primary_success"] += 1
                
                # Кешируем успешный результат
                if cache_key:
                    self.cache_result(cache_key, result)
                
                logger.debug(f"Основной обработчик '{self.name}' выполнен успешно")
                self.last_execution = {"mode": "primary", "fallback_name": None}
                return result
                
            except Exception as e:
                logger.warning(f"Основной обработчик '{self.name}' failed: {e}")
                
                if self.strategy == FallbackStrategy.FAIL_FAST:
                    self.stats["failures"] += 1
                    raise
                
                # Пытаемся fallback
                return await self._try_fallbacks(*args, exception=e, cache_key=cache_key, **kwargs)
        
        # Если основного обработчика нет, сразу пытаемся fallback
        return await self._try_fallbacks(*args, cache_key=cache_key, **kwargs)
    
    async def _try_fallbacks(self, *args, exception: Optional[Exception] = None, 
                           cache_key: Optional[str] = None, **kwargs) -> Any:
        """Попытаться выполнить fallback опции"""
        
        # Проверяем кеш как последний resort
        if cache_key:
            cached_result = self.get_cached_result(cache_key)
            if cached_result is not None:
                self.stats["cache_used"] += 1
                logger.info(f"Использован кеш как fallback для '{self.name}'")
                self.last_execution = {"mode": "cache", "fallback_name": "cache"}
                return cached_result
        
        # Пытаемся fallback опции по порядку приоритета
        for fallback in self.fallback_options:
            try:
                # Проверяем условие активации
                if fallback.condition:
                    if asyncio.iscoroutinefunction(fallback.condition):
                        condition_met = await fallback.condition(exception, *args, **kwargs)
                    else:
                        condition_met = fallback.condition(exception, *args, **kwargs)
                    
                    if not condition_met:
                        continue
                
                logger.info(f"Используется fallback '{fallback.name}' для '{self.name}'")
                
                if asyncio.iscoroutinefunction(fallback.handler):
                    result = await fallback.handler(*args, **kwargs)
                else:
                    result = fallback.handler(*args, **kwargs)
                
                self.stats["fallback_used"] += 1
                
                # Кешируем результат fallback
                if cache_key:
                    self.cache_result(cache_key, result, ttl=300)  # Короткий TTL для fallback
                
                logger.info(f"Fallback '{fallback.name}' для '{self.name}' выполнен успешно")
                self.last_execution = {"mode": "fallback", "fallback_name": fallback.name}
                return result
                
            except Exception as fallback_error:
                logger.error(f"Fallback '{fallback.name}' для '{self.name}' failed: {fallback_error}")
                continue
        
        # Все fallback опции исчерпаны
        self.stats["failures"] += 1
        original_error = exception or Exception("Основной обработчик недоступен")
        
        logger.error(f"Все fallback опции исчерпаны для '{self.name}': {original_error}")
        self.last_execution = {"mode": "error", "fallback_name": None}
        raise Exception(f"Все варианты выполнения исчерпаны для '{self.name}': {original_error}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику"""
        total = max(1, self.stats["total_calls"])
        
        return {
            "name": self.name,
            "strategy": self.strategy.value,
            "total_calls": self.stats["total_calls"],
            "primary_success": self.stats["primary_success"],
            "primary_success_rate": (self.stats["primary_success"] / total) * 100,
            "fallback_used": self.stats["fallback_used"],
            "fallback_rate": (self.stats["fallback_used"] / total) * 100,
            "cache_used": self.stats["cache_used"],
            "cache_hit_rate": (self.stats["cache_used"] / total) * 100,
            "failures": self.stats["failures"],
            "failure_rate": (self.stats["failures"] / total) * 100,
            "fallback_options": len(self.fallback_options),
            "cache_size": len(self.cache)
        }
    
    def clear_cache(self):
        """Очистить кеш"""
        cache_size = len(self.cache)
        self.cache.clear()
        logger.info(f"Очищен кеш для '{self.name}' ({cache_size} записей)")


# Предустановленные fallback функции
async def simple_error_message(*args, **kwargs) -> str:
    """Простое сообщение об ошибке"""
    return "❌ Сервис временно недоступен. Попробуйте позже."


async def cached_response_fallback(cache_key: str = None, *args, **kwargs) -> str:
    """Fallback с использованием кеша"""
    return "📄 Показываем последний сохраненный результат."


def _simplified_extraction_handler(provider=None, transcription: str = "", template_variables: Optional[Dict[str, Any]] = None,
                                  diarization_data: Optional[Dict[str, Any]] = None, *args, **kwargs) -> Dict[str, str]:
    """Обработчик fallback: упрощённое извлечение из транскрипта"""
    return _simple_text_extraction(transcription or "")


def _template_only_handler(provider=None, transcription: str = "", template_variables: Optional[Dict[str, Any]] = None,
                           diarization_data: Optional[Dict[str, Any]] = None, *args, **kwargs) -> Dict[str, str]:
    """Обработчик fallback: только шаблонные поля без анализа"""
    return _template_only_response()


def create_llm_fallback_manager() -> FallbackManager:
    """Создать fallback менеджер для LLM"""
    manager = FallbackManager("llm_service", FallbackStrategy.GRACEFUL_DEGRADATION)
    
    # Добавляем fallback опции с приоритетами (с совместимой сигнатурой)
    manager.add_fallback(
        "simplified_extraction",
        _simplified_extraction_handler,
        priority=10
    )
    
    manager.add_fallback(
        "template_only",
        _template_only_handler,
        priority=5
    )
    
    manager.add_fallback(
        "error_message", 
        simple_error_message,
        priority=1
    )
    
    return manager


def _simple_text_extraction(transcript: str) -> Dict[str, str]:
    """Простое извлечение данных без LLM"""
    words = transcript.split()
    word_count = len(words)
    
    # Простые эвристики
    participants = "Участники встречи"
    if word_count < 100:
        summary = "Короткая встреча или обсуждение"
    elif word_count < 500:
        summary = "Встреча средней продолжительности"
    else:
        summary = "Продолжительная встреча или детальное обсуждение"
    
    return {
        "participants": participants,
        "date": "Не указано",
        "time": "Не указано", 
        "agenda": "Автоматическое определение недоступно",
        "discussion": f"{summary}. Полный текст содержит {word_count} слов.",
        "decisions": "Решения требуют ручного анализа",
        "tasks": "Задачи требуют ручного анализа",
        "next_steps": "Следующие шаги требуют ручного анализа",
        "key_points": f"Встреча записана, {word_count} слов обработано"
    }


def _template_only_response() -> Dict[str, str]:
    """Ответ только с шаблоном"""
    return {
        "participants": "Информация недоступна",
        "date": "Информация недоступна",
        "time": "Информация недоступна",
        "agenda": "Сервис анализа временно недоступен",
        "discussion": "Для получения детального анализа попробуйте позже",
        "decisions": "Анализ решений недоступен",
        "tasks": "Анализ задач недоступен", 
        "next_steps": "Анализ следующих шагов недоступен",
        "key_points": "Автоматический анализ временно недоступен"
    }
