"""
Тесты для системы кэширования
"""

import pytest
import pytest_asyncio
import asyncio
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from src.performance.cache_system import (
    PerformanceCache,
    CacheEntry,
    cache_transcription,
    cache_llm_response,
    cache_diarization
)


@pytest_asyncio.fixture
async def temp_cache():
    """Фикстура для создания временного кеша"""
    temp_dir = tempfile.mkdtemp()
    cache = PerformanceCache(cache_dir=temp_dir, max_memory_mb=1)  # 1 MB для тестов
    yield cache
    # Очистка после теста
    await cache.clear()
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestPerformanceCache:
    """Тесты базовой функциональности кеша"""
    
    @pytest.mark.asyncio
    async def test_basic_set_get_memory(self, temp_cache):
        """Тест базового сохранения и чтения из памяти"""
        key = "test:key:123"
        value = {"data": "test_value", "number": 42}
        
        # Сохраняем в кеш
        result = await temp_cache.set(key, value)
        assert result is True
        
        # Читаем из кеша
        cached_value = await temp_cache.get(key)
        assert cached_value == value
        
        # Проверяем статистику
        stats = temp_cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 0
    
    @pytest.mark.asyncio
    async def test_basic_set_get_disk(self, temp_cache):
        """Тест сохранения и чтения с диска для больших объектов"""
        key = "test:large:456"
        # Создаем объект больше 1 MB
        large_value = {"data": "x" * (1024 * 1024 + 1000)}
        
        # Сохраняем в кеш (должен попасть на диск)
        result = await temp_cache.set(key, large_value)
        assert result is True
        
        # Проверяем, что файл создан на диске
        disk_file = temp_cache.disk_cache_dir / f"{key}.pkl"
        assert disk_file.exists()
        
        # Очищаем память, чтобы убедиться, что читаем с диска
        temp_cache.memory_cache.clear()
        
        # Читаем с диска
        cached_value = await temp_cache.get(key)
        assert cached_value == large_value
        
        # Проверяем статистику
        stats = temp_cache.get_stats()
        assert stats["disk_reads"] >= 1
        assert stats["disk_writes"] >= 1
    
    @pytest.mark.asyncio
    async def test_cache_miss(self, temp_cache):
        """Тест промахов кеша"""
        # Пытаемся прочитать несуществующий ключ
        result = await temp_cache.get("nonexistent:key")
        assert result is None
        
        # Проверяем статистику
        stats = temp_cache.get_stats()
        assert stats["misses"] == 1
        assert stats["hits"] == 0
    
    @pytest.mark.asyncio
    async def test_ttl_expiration(self, temp_cache):
        """Тест истечения срока действия TTL"""
        key = "test:ttl:789"
        value = "test_value_with_ttl"
        
        # Сохраняем с коротким TTL (1 секунда)
        await temp_cache.set(key, value, ttl=timedelta(seconds=1))
        
        # Сразу читаем - должно быть в кеше
        cached = await temp_cache.get(key)
        assert cached == value
        
        # Ждем истечения TTL
        await asyncio.sleep(1.5)
        
        # Теперь должен быть cache miss
        cached = await temp_cache.get(key)
        assert cached is None
        
        # Проверяем, что запись удалена
        assert key not in temp_cache.memory_cache
    
    @pytest.mark.asyncio
    async def test_ttl_by_cache_type(self, temp_cache):
        """Тест разных TTL для разных типов кеша"""
        # Проверяем TTL для разных типов
        assert temp_cache.default_ttl["transcription"] == timedelta(hours=24)
        assert temp_cache.default_ttl["llm_response"] == timedelta(hours=6)
        assert temp_cache.default_ttl["file_info"] == timedelta(hours=1)
        assert temp_cache.default_ttl["user_data"] == timedelta(minutes=30)
        assert temp_cache.default_ttl["template"] == timedelta(hours=12)
        assert temp_cache.default_ttl["diarization"] == timedelta(hours=24)
    
    @pytest.mark.asyncio
    async def test_lru_eviction(self, temp_cache):
        """Тест LRU вытеснения при переполнении памяти"""
        # Сохраняем несколько объектов, которые заполнят память (max 1 MB)
        keys = []
        for i in range(10):
            key = f"test:lru:{i}"
            # Каждый объект ~150 KB
            value = {"data": "x" * (150 * 1024)}
            await temp_cache.set(key, value)
            keys.append(key)
            await asyncio.sleep(0.01)  # Небольшая задержка для different timestamps
        
        # Проверяем, что произошли вытеснения
        stats = temp_cache.get_stats()
        assert stats["evictions"] > 0
        
        # Первые ключи должны быть вытеснены (LRU)
        first_key = await temp_cache.get(keys[0])
        assert first_key is None  # Был вытеснен
        
        # Последние ключи должны быть в кеше
        last_key = await temp_cache.get(keys[-1])
        assert last_key is not None
    
    @pytest.mark.asyncio
    async def test_cleanup_expired(self, temp_cache):
        """Тест очистки просроченных записей"""
        # Создаем несколько записей с разными TTL
        await temp_cache.set("key1", "value1", ttl=timedelta(seconds=0.5))
        await temp_cache.set("key2", "value2", ttl=timedelta(seconds=10))
        await temp_cache.set("key3", "value3", ttl=timedelta(seconds=0.5))
        
        # Ждем истечения коротких TTL
        await asyncio.sleep(1)
        
        # Запускаем очистку
        await temp_cache.cleanup_expired()
        
        # Проверяем, что просроченные удалены
        assert await temp_cache.get("key1") is None
        assert await temp_cache.get("key3") is None
        
        # А непросроченные остались
        assert await temp_cache.get("key2") == "value2"
    
    @pytest.mark.asyncio
    async def test_clear_all(self, temp_cache):
        """Тест полной очистки кеша"""
        # Добавляем несколько записей
        await temp_cache.set("key1", "value1")
        await temp_cache.set("key2", "value2")
        await temp_cache.set("key3", "value3")
        
        # Очищаем весь кеш
        await temp_cache.clear()
        
        # Проверяем, что все удалено
        assert await temp_cache.get("key1") is None
        assert await temp_cache.get("key2") is None
        assert await temp_cache.get("key3") is None
        
        # Проверяем счетчики
        assert len(temp_cache.memory_cache) == 0
        assert temp_cache.current_memory_usage == 0
    
    @pytest.mark.asyncio
    async def test_clear_by_type(self, temp_cache):
        """Тест очистки кеша по типу"""
        # Добавляем записи разных типов
        await temp_cache.set("key1", "value1", cache_type="transcription")
        await temp_cache.set("key2", "value2", cache_type="llm_response")
        await temp_cache.set("key3", "value3", cache_type="transcription")
        
        # Очищаем только транскрипции
        await temp_cache.clear(cache_type="transcription")
        
        # Проверяем результат
        assert await temp_cache.get("key1") is None
        assert await temp_cache.get("key3") is None
        assert await temp_cache.get("key2") == "value2"  # LLM остался
    
    @pytest.mark.asyncio
    async def test_statistics(self, temp_cache):
        """Тест корректности статистики кеша"""
        # Создаем несколько операций
        await temp_cache.set("key1", "value1")
        await temp_cache.set("key2", "value2")
        
        # Попадания
        await temp_cache.get("key1")
        await temp_cache.get("key2")
        await temp_cache.get("key1")
        
        # Промахи
        await temp_cache.get("nonexistent1")
        await temp_cache.get("nonexistent2")
        
        # Получаем статистику
        stats = temp_cache.get_stats()
        
        # Проверяем счетчики
        assert stats["hits"] == 3
        assert stats["misses"] == 2
        
        # Проверяем hit rate (3/(3+2) = 60%)
        assert stats["hit_rate_percent"] == 60.0
        
        # Проверяем информацию о памяти
        assert "memory_usage_mb" in stats
        assert "memory_usage_percent" in stats
        assert "memory_entries" in stats
        assert "disk_entries" in stats
    
    @pytest.mark.asyncio
    async def test_key_generation(self, temp_cache):
        """Тест генерации ключей кеша"""
        # Одинаковые данные должны давать одинаковые ключи
        key1 = temp_cache._generate_key("prefix", {"a": 1, "b": 2})
        key2 = temp_cache._generate_key("prefix", {"b": 2, "a": 1})  # Другой порядок
        assert key1 == key2
        
        # Разные данные - разные ключи
        key3 = temp_cache._generate_key("prefix", {"a": 1, "b": 3})
        assert key1 != key3
        
        # Разные префиксы - разные ключи
        key4 = temp_cache._generate_key("other", {"a": 1, "b": 2})
        assert key1 != key4
        
        # Проверяем формат ключа
        assert ":" in key1
        assert key1.startswith("prefix:")
    
    @pytest.mark.asyncio
    async def test_delete_operation(self, temp_cache):
        """Тест удаления конкретной записи"""
        key = "test:delete:key"
        await temp_cache.set(key, "test_value")
        
        # Проверяем, что запись существует
        assert await temp_cache.get(key) == "test_value"
        
        # Удаляем
        result = await temp_cache.delete(key)
        assert result is True
        
        # Проверяем, что запись удалена
        assert await temp_cache.get(key) is None
    
    @pytest.mark.asyncio
    async def test_access_count_updates(self, temp_cache):
        """Тест обновления счетчика обращений"""
        key = "test:access:count"
        await temp_cache.set(key, "test_value")
        
        # Читаем несколько раз
        for _ in range(5):
            await temp_cache.get(key)
        
        # Проверяем счетчик обращений
        entry = temp_cache.memory_cache[key]
        assert entry.access_count == 5
    
    @pytest.mark.asyncio
    async def test_last_accessed_updates(self, temp_cache):
        """Тест обновления времени последнего доступа"""
        key = "test:last:accessed"
        await temp_cache.set(key, "test_value")
        
        # Получаем начальное время
        entry1 = temp_cache.memory_cache[key]
        first_accessed = entry1.last_accessed
        
        # Ждем немного
        await asyncio.sleep(0.1)
        
        # Читаем снова
        await temp_cache.get(key)
        
        # Проверяем, что время обновилось
        entry2 = temp_cache.memory_cache[key]
        assert entry2.last_accessed > first_accessed


class TestCacheDecorators:
    """Тесты декораторов кеширования"""
    
    @pytest.mark.asyncio
    async def test_cache_decorator_basic(self, temp_cache):
        """Тест базового использования декоратора"""
        call_count = 0
        
        @cache_transcription(ttl=timedelta(seconds=10))
        async def test_function(x, y):
            nonlocal call_count
            call_count += 1
            return x + y
        
        # Первый вызов - функция выполняется
        result1 = await test_function(2, 3)
        assert result1 == 5
        assert call_count == 1
        
        # Второй вызов - берется из кеша
        result2 = await test_function(2, 3)
        assert result2 == 5
        assert call_count == 1  # Функция не вызывалась повторно
        
        # Вызов с другими аргументами - функция выполняется
        result3 = await test_function(5, 7)
        assert result3 == 12
        assert call_count == 2
    
    @pytest.mark.asyncio
    async def test_cache_decorator_with_kwargs(self, temp_cache):
        """Тест декоратора с именованными аргументами"""
        call_count = 0
        
        @cache_llm_response()
        async def test_function(name, age=25):
            nonlocal call_count
            call_count += 1
            return f"{name} is {age} years old"
        
        # Вызов с kwargs
        result1 = await test_function("Alice", age=30)
        assert result1 == "Alice is 30 years old"
        assert call_count == 1
        
        # Повторный вызов - из кеша
        result2 = await test_function("Alice", age=30)
        assert result2 == "Alice is 30 years old"
        assert call_count == 1
        
        # Другие kwargs
        result3 = await test_function("Bob", age=25)
        assert result3 == "Bob is 25 years old"
        assert call_count == 2
    
    @pytest.mark.asyncio
    async def test_cache_decorator_class_method(self, temp_cache):
        """Тест декоратора для методов класса"""
        
        class TestClass:
            def __init__(self):
                self.call_count = 0
            
            @cache_diarization()
            async def cached_method(self, value):
                self.call_count += 1
                return value * 2
        
        obj = TestClass()
        
        # Первый вызов
        result1 = await obj.cached_method(10)
        assert result1 == 20
        assert obj.call_count == 1
        
        # Второй вызов - из кеша
        result2 = await obj.cached_method(10)
        assert result2 == 20
        assert obj.call_count == 1  # Не вызывалось повторно
    
    @pytest.mark.asyncio
    async def test_cache_decorator_complex_args(self, temp_cache):
        """Тест декоратора со сложными аргументами"""
        call_count = 0
        
        @cache_transcription()
        async def test_function(data: dict, items: list):
            nonlocal call_count
            call_count += 1
            return {"processed": True, "count": len(items)}
        
        # Вызов со сложными аргументами
        result1 = await test_function({"key": "value"}, [1, 2, 3])
        assert result1["processed"] is True
        assert result1["count"] == 3
        assert call_count == 1
        
        # Повторный вызов с теми же данными
        result2 = await test_function({"key": "value"}, [1, 2, 3])
        assert result2["processed"] is True
        assert call_count == 1  # Из кеша
    
    @pytest.mark.asyncio
    async def test_different_cache_types(self, temp_cache):
        """Тест разных типов кеша для декораторов"""
        transcription_calls = 0
        llm_calls = 0
        
        @cache_transcription()
        async def transcription_func():
            nonlocal transcription_calls
            transcription_calls += 1
            return "transcription_result"
        
        @cache_llm_response()
        async def llm_func():
            nonlocal llm_calls
            llm_calls += 1
            return "llm_result"
        
        # Вызываем обе функции
        await transcription_func()
        await llm_func()
        
        # Повторные вызовы - из кеша
        await transcription_func()
        await llm_func()
        
        # Проверяем, что каждая функция вызвана только один раз
        assert transcription_calls == 1
        assert llm_calls == 1


class TestCacheIntegration:
    """Интеграционные тесты кеша"""
    
    @pytest.mark.asyncio
    async def test_disk_to_memory_promotion(self, temp_cache):
        """Тест автоматической загрузки с диска в память при повторном чтении"""
        key = "test:promotion"
        # Маленький объект
        value = {"data": "small_value"}
        
        # Сохраняем на диск вручную
        await temp_cache._save_to_disk(key, CacheEntry(
            key=key,
            value=value,
            created_at=datetime.now(),
            expires_at=datetime.now() + timedelta(hours=1),
            size_bytes=100,
            metadata={}
        ))
        
        # Читаем - должен загрузиться в память
        result = await temp_cache.get(key)
        assert result == value
        
        # Проверяем, что теперь в памяти
        assert key in temp_cache.memory_cache
    
    @pytest.mark.asyncio
    async def test_concurrent_access(self, temp_cache):
        """Тест одновременного доступа к кешу"""
        key = "test:concurrent"
        await temp_cache.set(key, "test_value")
        
        # Одновременные чтения
        results = await asyncio.gather(
            temp_cache.get(key),
            temp_cache.get(key),
            temp_cache.get(key),
            temp_cache.get(key),
            temp_cache.get(key)
        )
        
        # Все должны получить одинаковое значение
        assert all(r == "test_value" for r in results)
    
    @pytest.mark.asyncio
    async def test_cache_size_calculation(self, temp_cache):
        """Тест правильного подсчета размера объектов"""
        # Маленький объект
        small_value = "small"
        small_size = temp_cache._calculate_size(small_value)
        assert small_size > 0
        assert not temp_cache._should_cache_to_disk(small_size)
        
        # Большой объект (> 1 MB)
        large_value = "x" * (1024 * 1024 + 1000)
        large_size = temp_cache._calculate_size(large_value)
        assert large_size > 1024 * 1024
        assert temp_cache._should_cache_to_disk(large_size)
    
    @pytest.mark.asyncio
    async def test_corrupted_disk_cache(self, temp_cache):
        """Тест обработки поврежденного дискового кеша"""
        key = "test:corrupted"
        
        # Создаем поврежденный файл кеша
        disk_path = temp_cache.disk_cache_dir / f"{key}.pkl"
        disk_path.write_text("corrupted data")
        
        # Попытка чтения должна вернуть None
        result = await temp_cache.get(key)
        assert result is None
        
        # Файл должен быть помечен как поврежденный и удален
        # (проверяем, что система обработала ошибку корректно)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

