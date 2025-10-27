# Исправление кеширования для Telegram файлов

## Дата: 27 октября 2025

## Проблема

При повторной отправке одного и того же Telegram файла кеш полного результата не работал, потому что использовался `file_id`, который Telegram генерирует **новый для каждого сообщения**:

```
Первый раз:  file_id=ABC123...  → ключ кеша: hash(ABC123...) → Cache MISS → 5-10 мин
Второй раз:  file_id=XYZ789...  → ключ кеша: hash(XYZ789...) → Cache MISS → 1-2 мин
```

Из-за этого при повторной обработке того же файла:
- ✅ Транскрипция кешировалась (использует SHA-256 хеш содержимого) 
- ❌ Полный результат (с LLM) НЕ кешировался (использовал меняющийся file_id)
- ⏱️ Время обработки: ~1-2 минуты вместо 0.1 секунды

## Решение

Использовать **SHA-256 хеш содержимого файла** в качестве идентификатора для генерации ключа кеша полного результата (аналогично исправлению для внешних файлов в `EXTERNAL_FILE_CACHING_FIX.md`).

## Изменения

### 1. Изменен порядок операций в `process_file`
**Файл:** `src/services/optimized_processing_service.py` (метод `process_file`, строки 80-173)

**Старый порядок:**
1. Генерация ключа кеша (использует file_id)
2. Проверка кеша
3. Скачивание файла
4. Обработка

**Новый порядок:**
1. Скачивание файла (для Telegram) / использование существующего (для external)
2. Вычисление SHA-256 хеша содержимого файла
3. Генерация ключа кеша (использует file_hash)
4. Проверка кеша
5. Если HIT → удалить файл и вернуть результат ✅
6. Если MISS → продолжить обработку

```python
# Шаг 1: Получаем путь к файлу
if request.is_external_file:
    temp_file_path = request.file_path
else:
    # Для Telegram файлов - скачиваем
    temp_file_path = await self._download_telegram_file(request)
    cache_check_only = True

# Шаг 2: Вычисляем хеш файла
file_hash = await self._calculate_file_hash(temp_file_path)

# Шаг 3: Генерируем ключ кеша с хешем
cache_key = self._generate_result_cache_key(request, file_hash)

# Шаг 4: Проверяем кеш
cached_result = await performance_cache.get(cache_key)

if cached_result:
    # Удаляем скачанный файл, если он был загружен только для проверки кеша
    if cache_check_only and temp_file_path and os.path.exists(temp_file_path):
        await self._cleanup_temp_file(temp_file_path)
    return cached_result
```

### 2. Добавлен метод `_download_telegram_file`
**Файл:** `src/services/optimized_processing_service.py` (строки 1046-1073)

Новый вспомогательный метод для скачивания Telegram файлов:

```python
async def _download_telegram_file(self, request: ProcessingRequest) -> str:
    """Скачать Telegram файл и вернуть путь"""
    file_url = await self.file_service.get_telegram_file_url(request.file_id)
    temp_file_path = f"temp/{request.file_name}"
    
    async with OptimizedHTTPClient() as http_client:
        result = await http_client.download_file(file_url, temp_file_path)
        
        if not result["success"]:
            raise ProcessingError(...)
    
    logger.info(f"Файл скачан: {temp_file_path} ({result['bytes_downloaded']} байт)")
    return temp_file_path
```

### 3. Изменена генерация ключа кеша
**Файл:** `src/services/optimized_processing_service.py` (метод `_generate_result_cache_key`, строки 1086-1107)

**Было:**
```python
def _generate_result_cache_key(self, request: ProcessingRequest) -> str:
    if request.is_external_file and request.file_url:
        file_identifier = request.file_url
    elif request.file_id:
        file_identifier = request.file_id  # ← Меняется каждый раз!
    else:
        file_identifier = request.file_path
    
    key_data = {
        "file_identifier": file_identifier,
        "template_id": request.template_id,
        "llm_provider": request.llm_provider,
        "language": request.language,
        "is_external_file": request.is_external_file,
        "participants_list": request.participants_list
    }
    return performance_cache._generate_key("full_result", key_data)
```

**Стало:**
```python
def _generate_result_cache_key(self, request: ProcessingRequest, file_hash: str) -> str:
    """Генерировать ключ кэша для полного результата
    
    Args:
        request: Запрос на обработку
        file_hash: SHA-256 хеш содержимого файла
    """
    key_data = {
        "file_hash": file_hash,  # ← Используем хеш содержимого
        "template_id": request.template_id,
        "llm_provider": request.llm_provider,
        "language": request.language,
        "participants_list": request.participants_list,
        "meeting_topic": request.meeting_topic,      # ← Добавлено
        "meeting_date": request.meeting_date,        # ← Добавлено
        "meeting_time": request.meeting_time,        # ← Добавлено
        "speaker_mapping": request.speaker_mapping   # ← Добавлено
    }
    return performance_cache._generate_key("full_result", key_data)
```

**Важно:** Добавлены дополнительные поля в ключ кеша:
- `meeting_topic` - тема встречи
- `meeting_date` - дата встречи
- `meeting_time` - время встречи
- `speaker_mapping` - сопоставление спикеров

Это гарантирует, что при изменении этих параметров будет создан новый результат, а не использован старый из кеша.

### 4. Обновлен метод `_process_file_optimized`
**Файл:** `src/services/optimized_processing_service.py` (строки 208-292)

Добавлен параметр `temp_file_path` для передачи уже скачанного файла:

```python
async def _process_file_optimized(self, request: ProcessingRequest, 
                                processing_metrics, progress_tracker=None, 
                                temp_file_path: str = None) -> ProcessingResult:
    """
    Args:
        temp_file_path: Путь к уже скачанному файлу (если None, файл будет скачан)
    """
    
    # Если путь к файлу не передан, скачиваем файл (обратная совместимость)
    if temp_file_path is None:
        # ... логика скачивания ...
    else:
        # Файл уже скачан, просто получаем метрики
        if os.path.exists(temp_file_path):
            file_size = os.path.getsize(temp_file_path)
            processing_metrics.file_size_bytes = file_size
            processing_metrics.download_duration = 0.0
            logger.debug(f"Используем уже скачанный файл: {temp_file_path}")
```

## Результат

### До исправления:
```
Запрос 1: file_id=ABC123 → cache key: hash(ABC123+...) → MISS → 5-10 мин
Запрос 2: file_id=XYZ789 → cache key: hash(XYZ789+...) → MISS → 1-2 мин ❌
```

### После исправления:
```
Запрос 1: file_hash=f3a2c1... → cache key: hash(f3a2c1...+...) → MISS → 5-10 мин
Запрос 2: file_hash=f3a2c1... → cache key: hash(f3a2c1...+...) → HIT → 0.1 сек ✅
```

## Ожидаемые логи

### При первом запросе (Cache MISS):
```
INFO | Файл скачан: temp/audio.m4a (12345678 байт)
DEBUG | Вычислен хеш файла: f3a2c1b4d5e6f789
❌ INFO | Кеш не найден для audio.m4a (file_hash: f3a2c1b4d5e6f789), начинаем обработку
... [5-10 минут обработки] ...
💾 INFO | Результат закеширован для audio.m4a (file_hash: f3a2c1b4d5e6f789)
```

### При повторном запросе того же файла (Cache HIT):
```
INFO | Файл скачан: temp/audio.m4a (12345678 байт)
DEBUG | Вычислен хеш файла: f3a2c1b4d5e6f789
✅ INFO | Найден кэшированный результат для audio.m4a (file_hash: f3a2c1b4d5e6f789)
DEBUG | Удален временный файл: temp/audio.m4a
```

## Преимущества решения

1. **✅ Работает для всех типов файлов:**
   - Telegram файлы: используют хеш содержимого
   - Внешние файлы (URL): используют хеш содержимого
   - Одинаковый механизм для всех источников

2. **✅ Детерминированность:**
   - Один и тот же файл всегда дает один и тот же хеш
   - Не зависит от случайных идентификаторов (file_id, временные имена)

3. **✅ Учет всех параметров:**
   - Хеш файла
   - Шаблон
   - LLM провайдер
   - Язык
   - Список участников
   - Информация о встрече (тема, дата, время)
   - Сопоставление спикеров

4. **✅ Эффективность:**
   - Кеш проверяется сразу после скачивания
   - При cache hit файл удаляется, экономя место
   - SHA-256 хеш вычисляется быстро даже для больших файлов (чанками)

5. **✅ Обратная совместимость:**
   - `_process_file_optimized` может работать как со старым вызовом (без `temp_file_path`), так и с новым

## Тестирование

### Сценарий 1: Один и тот же файл, одни и те же параметры
```
1. Отправить audio.m4a → Cache MISS → 5-10 мин
2. Отправить тот же audio.m4a → Cache HIT → 0.1 сек ✅
```

### Сценарий 2: Один и тот же файл, разные шаблоны
```
1. audio.m4a + шаблон "Стандартный" → Cache MISS → обработка
2. audio.m4a + шаблон "Деловая встреча" → Cache MISS → обработка ✅
3. audio.m4a + шаблон "Стандартный" → Cache HIT → мгновенно ✅
```

### Сценарий 3: Один и тот же файл, разные списки участников
```
1. audio.m4a + участники [A, B, C] → Cache MISS → обработка
2. audio.m4a + участники [A, B, C, D] → Cache MISS → обработка ✅
3. audio.m4a + участники [A, B, C] → Cache HIT → мгновенно ✅
```

### Сценарий 4: Разные файлы с одинаковым содержимым
```
1. file1.m4a (содержимое X) → Cache MISS → обработка
2. file2.m4a (содержимое X) → Cache HIT → мгновенно ✅
   (хеш содержимого одинаковый!)
```

## Связанные документы

- `EXTERNAL_FILE_CACHING_FIX.md` - Исправление кеширования для внешних файлов (URL)
- `CACHE_TESTING_REPORT.md` - Отчет о тестировании системы кеширования
- `docs/PERFORMANCE_OPTIMIZATION.md` - Документация по оптимизации производительности

---

**Статус:** ✅ Реализовано  
**Версия:** 27 октября 2025

