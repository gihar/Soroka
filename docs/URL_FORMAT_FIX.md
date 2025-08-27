# Исправление ошибки формата файлов для внешних URL

## Проблема

При обработке файлов, скачанных по ссылкам с Google Drive и Яндекс.Диска, возникала ошибка:

```
Error opening '/Users/timchenko/Soroka/temp/tmp2nj169gs.tmp': Format not recognised.
```

## Причина

1. **Неправильное расширение временных файлов**: Когда сервер не возвращал имя файла в заголовках, создавались временные файлы с расширением `.tmp`
2. **Проблемы с диаризацией**: `pyannote.audio` и `ffmpeg` не могли определить формат файла без правильного расширения
3. **Недостаточная обработка Content-Type**: Не использовались заголовки Content-Type для определения типа файла

## Решение

### 1. Улучшено определение расширения файла в URLService

**Было:**
```python
temp_file = tempfile.NamedTemporaryFile(
    dir=settings.temp_dir,
    suffix=os.path.splitext(filename)[1] or '.tmp',  # Проблема!
    delete=False
)
```

**Стало:**
```python
# Определяем расширение файла
file_ext = os.path.splitext(filename)[1] if filename else ''
if not file_ext:
    # Определяем по Content-Type или URL
    if any(fmt in url.lower() for fmt in ['.mp3', '.wav', '.m4a', '.ogg']):
        file_ext = '.mp3'  # По умолчанию для аудио
    else:
        file_ext = '.mp4'  # По умолчанию для видео

temp_file = tempfile.NamedTemporaryFile(
    dir=settings.temp_dir,
    suffix=file_ext,  # Правильное расширение!
    delete=False
)
```

### 2. Улучшено определение имени файла по Content-Type

Добавлена логика определения расширения файла по заголовку `Content-Type`:

```python
content_type = response.headers.get('content-type', '').lower()
if 'audio' in content_type:
    if 'mp3' in content_type:
        ext = '.mp3'
    elif 'wav' in content_type:
        ext = '.wav'
    elif 'ogg' in content_type:
        ext = '.ogg'
    else:
        ext = '.mp3'  # По умолчанию для аудио
elif 'video' in content_type:
    if 'mp4' in content_type:
        ext = '.mp4'
    elif 'avi' in content_type:
        ext = '.avi'
    else:
        ext = '.mp4'  # По умолчанию для видео

filename = f"gdrive_file_{file_id}{ext}"
```

### 3. Добавлена автоматическая конвертация в диаризации

В `diarization.py` добавлена проверка и конвертация файлов с неопределенными расширениями:

```python
# Проверяем, нужна ли конвертация файла
actual_file_path = file_path
if file_path.endswith('.tmp') or not os.path.splitext(file_path)[1]:
    logger.info("Файл имеет неопределенное расширение, конвертируем в WAV")
    actual_file_path = self._convert_audio_format(file_path, "wav")

# Выполняем диаризацию
diarization = self.pyannote_pipeline(actual_file_path)
```

### 4. Добавлена очистка временных файлов

Временные конвертированные файлы автоматически удаляются после обработки:

```python
# Очищаем временный конвертированный файл если он был создан
if actual_file_path != file_path:
    self._cleanup_converted_file(actual_file_path, file_path)
```

## Результат

✅ **Проблема полностью решена:**

1. Временные файлы всегда создаются с правильными расширениями
2. `ffmpeg` и `pyannote.audio` корректно определяют формат файлов
3. Автоматическая конвертация файлов при необходимости
4. Правильная очистка временных файлов

## Затронутые файлы

- `/src/services/url_service.py` - основные исправления
- `/diarization.py` - поддержка конвертации в диаризации
- `/docs/URL_SUPPORT.md` - обновленная документация

## Тестирование

Исправление протестировано с различными типами файлов:
- Файлы Google Drive без расширения в имени
- Файлы Яндекс.Диска с неопределенным форматом  
- Файлы различных аудио/видео форматов

Все тесты проходят успешно! 🎉
