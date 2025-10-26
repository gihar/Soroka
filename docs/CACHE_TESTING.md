# Тестирование системы кеширования

## 📋 Обзор

Система кеширования Soroka полностью покрыта автоматизированными тестами. Файл с тестами: `tests/test_cache_system.py`

## ✅ Статус тестирования

- **Всего тестов:** 23
- **Пройдено:** 23 (100%)
- **Покрытие:** Все основные функции системы кеширования

## 🧪 Что тестируется

### 1. Базовые операции (4 теста)
- Сохранение и чтение из памяти
- Сохранение и чтение с диска (большие объекты > 1 МБ)
- Обработка cache miss
- Генерация уникальных ключей

### 2. TTL (3 теста)
- Автоматическое истечение срока действия
- Разные TTL для разных типов данных
- Очистка просроченных записей

### 3. LRU вытеснение (1 тест)
- Автоматическое удаление старых записей при переполнении памяти

### 4. Очистка (3 теста)
- Полная очистка кеша
- Очистка по типу данных
- Удаление конкретной записи

### 5. Статистика (3 теста)
- Корректность подсчета hit rate
- Обновление счетчиков обращений
- Обновление времени последнего доступа

### 6. Декораторы (5 тестов)
- Базовое кеширование функций
- Кеширование с kwargs
- Кеширование методов классов
- Сложные аргументы (dict, list)
- Разные типы кеша

### 7. Интеграция (4 теста)
- Автоматическая загрузка с диска в память
- Одновременный доступ
- Подсчет размера объектов
- Обработка поврежденных файлов

## 🚀 Запуск тестов

### Все тесты кеша
```bash
source venv/bin/activate
python -m pytest tests/test_cache_system.py -v
```

### Конкретный класс тестов
```bash
# Базовая функциональность
python -m pytest tests/test_cache_system.py::TestPerformanceCache -v

# Декораторы
python -m pytest tests/test_cache_system.py::TestCacheDecorators -v

# Интеграция
python -m pytest tests/test_cache_system.py::TestCacheIntegration -v
```

### Конкретный тест
```bash
python -m pytest tests/test_cache_system.py::TestPerformanceCache::test_basic_set_get_memory -v
```

### С подробным выводом
```bash
python -m pytest tests/test_cache_system.py -vv -s
```

## 📊 Пример вывода

```
============================= test session starts ==============================
collected 23 items

tests/test_cache_system.py::TestPerformanceCache::test_basic_set_get_memory PASSED
tests/test_cache_system.py::TestPerformanceCache::test_basic_set_get_disk PASSED
tests/test_cache_system.py::TestPerformanceCache::test_cache_miss PASSED
...
======================== 23 passed in 3.03s ========================
```

## 🔍 Структура тестов

```python
# Фикстура для временного кеша
@pytest_asyncio.fixture
async def temp_cache():
    """Создает изолированный кеш для каждого теста"""
    temp_dir = tempfile.mkdtemp()
    cache = PerformanceCache(cache_dir=temp_dir, max_memory_mb=1)
    yield cache
    await cache.clear()
    shutil.rmtree(temp_dir)

# Пример теста
@pytest.mark.asyncio
async def test_basic_set_get_memory(temp_cache):
    """Тест базового сохранения и чтения"""
    await temp_cache.set("key", "value")
    result = await temp_cache.get("key")
    assert result == "value"
```

## 📝 Добавление новых тестов

### Шаг 1: Импортируйте необходимые модули
```python
import pytest
import pytest_asyncio
from src.performance.cache_system import PerformanceCache
```

### Шаг 2: Используйте фикстуру `temp_cache`
```python
@pytest.mark.asyncio
async def test_my_feature(temp_cache):
    # Ваш тест
    pass
```

### Шаг 3: Проверяйте результаты
```python
# Проверка значения
result = await temp_cache.get("key")
assert result == expected_value

# Проверка статистики
stats = temp_cache.get_stats()
assert stats["hits"] == 1
```

## 🎯 Best Practices

### 1. Изоляция тестов
- Используйте фикстуру `temp_cache` для каждого теста
- Не зависьте от глобального состояния
- Очищайте кеш после теста

### 2. Проверка статистики
```python
# Проверяйте счетчики
stats = temp_cache.get_stats()
assert stats["hits"] > 0
assert stats["misses"] == 0
```

### 3. Тестирование асинхронного кода
```python
# Используйте pytest.mark.asyncio
@pytest.mark.asyncio
async def test_async_operation(temp_cache):
    await temp_cache.set("key", "value")
    result = await temp_cache.get("key")
    assert result == "value"
```

### 4. Тестирование TTL
```python
# Используйте asyncio.sleep для проверки истечения
await temp_cache.set("key", "value", ttl=timedelta(seconds=1))
await asyncio.sleep(1.5)
result = await temp_cache.get("key")
assert result is None  # Истекло
```

### 5. Тестирование больших объектов
```python
# Создавайте объекты > 1 МБ для проверки дискового кеша
large_value = {"data": "x" * (1024 * 1024 + 1000)}
await temp_cache.set("key", large_value)

# Проверяйте файл на диске
disk_file = temp_cache.disk_cache_dir / "key.pkl"
assert disk_file.exists()
```

## 📈 Метрики качества

### Текущие показатели
- **Покрытие кода:** ~100% основных функций
- **Время выполнения:** ~3 секунды
- **Успешность:** 23/23 (100%)

### Целевые показатели
- ✅ Покрытие > 90%
- ✅ Все тесты проходят
- ✅ Время выполнения < 5 секунд
- ✅ Нет flaky тестов

## 🐛 Отладка

### Просмотр логов кеша
```bash
# Запуск с выводом логов
python -m pytest tests/test_cache_system.py -v -s --log-cli-level=DEBUG
```

### Проверка состояния кеша
```python
# В тесте
print(temp_cache.get_stats())
print(f"Memory entries: {len(temp_cache.memory_cache)}")
print(f"Disk files: {list(temp_cache.disk_cache_dir.glob('*.pkl'))}")
```

### Отладка конкретного теста
```bash
# С точкой останова
python -m pytest tests/test_cache_system.py::test_name -v -s --pdb
```

## 📚 Связанные документы

- [Отчет о тестировании](../CACHE_TESTING_REPORT.md) — подробный отчет с результатами
- [Руководство по производительности](PERFORMANCE_OPTIMIZATION.md) — оптимизация системы
- [Исходный код кеша](../src/performance/cache_system.py) — реализация

## 🤝 Вклад

При добавлении нового функционала в систему кеширования:

1. Напишите тесты **ДО** реализации (TDD)
2. Убедитесь, что все существующие тесты проходят
3. Добавьте документацию к новым тестам
4. Обновите этот файл при необходимости

## ✅ Чеклист перед коммитом

- [ ] Все тесты проходят (`pytest tests/test_cache_system.py`)
- [ ] Добавлены тесты для нового функционала
- [ ] Покрытие не уменьшилось
- [ ] Нет flaky тестов (запустите 3-5 раз)
- [ ] Документация обновлена

