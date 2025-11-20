# Руководство по конфигурации

Soroka настраивается через переменные окружения, обычно определенные в файле `.env`.

## Основные настройки

| Переменная | Описание | Обязательно | По умолчанию |
|------------|----------|-------------|--------------|
| `TELEGRAM_TOKEN` | Ваш токен Telegram бота от @BotFather | Да | - |
| `DATABASE_URL` | Строка подключения к базе данных | Нет | `sqlite:///bot.db` |
| `LOG_LEVEL` | Уровень логирования (DEBUG, INFO, WARNING, ERROR) | Нет | `INFO` |

## LLM Провайдеры

Вы должны настроить хотя бы одного LLM провайдера.

### OpenAI
```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4-turbo
```

### Anthropic (Claude)
```env
ANTHROPIC_API_KEY=sk-ant-...
```

### Yandex GPT
```env
YANDEX_API_KEY=...
YANDEX_FOLDER_ID=...
```

## Транскрипция и Диаризация

Управление обработкой аудио.

| Переменная | Описание | Опции | По умолчанию |
|------------|----------|-------|--------------|
| `TRANSCRIPTION_MODE` | Движок транскрипции | `local`, `cloud`, `hybrid`, `speechmatics`, `leopard` | `local` |
| `ENABLE_DIARIZATION` | Включить разделение спикеров | `true`, `false` | `false` |
| `DIARIZATION_PROVIDER` | Движок диаризации | `whisperx`, `pyannote`, `picovoice` | `whisperx` |

### Ключи облачных провайдеров
- `GROQ_API_KEY`: Для быстрой облачной транскрипции через Groq.
- `SPEECHMATICS_API_KEY`: Для Speechmatics API.
- `DEEGRAM_API_KEY`: Для Deepgram API.
- `PICOVOICE_ACCESS_KEY`: Для Picovoice (Leopard/Falcon).

## Производительность и Лимиты

```env
# Макс. размер файла для загрузки в Telegram (байты)
TELEGRAM_MAX_FILE_SIZE=20971520  # 20MB

# Макс. размер файла для внешних ссылок (байты)
MAX_EXTERNAL_FILE_SIZE=52428800  # 50MB

# Защита от OOM
OOM_MAX_MEMORY_PERCENT=90.0
```

## Продвинутые функции

- `ENABLE_SPEAKER_MAPPING`: Включить умное сопоставление спикеров с известными участниками (по умолчанию: `true`).
- `ENABLE_PROMPT_CACHING`: Использовать кэширование промптов для экономии (по умолчанию: `true`).
- `ENABLE_CLEANUP`: Автоудаление временных файлов (по умолчанию: `true`).
