# Исправление ошибок валидации Pydantic в Deepgram SDK

## Проблема

При использовании Deepgram SDK версии 3.x-5.x возникали ошибки валидации Pydantic:

```
ListenV1Response.results.utterances.X.words.Y.speaker_confidence
  Input should be a valid integer, got a number with a fractional part [type=int_from_float, input_value=0.030712605, input_type=float]

ListenV1AcceptedResponse.request_id
  Field required [type=missing, input_value={'metadata': {...}}, input_type=dict]
```

### Причина

Несоответствие между тем, что возвращает Deepgram API, и моделями Pydantic в SDK:

1. **`speaker_confidence`** - SDK ожидает `int`, но API возвращает `float` (например, `0.030712605`)
2. **`request_id`** - поле объявлено как обязательное, но в некоторых ответах API отсутствует

## Решение

Переход от использования Deepgram SDK к прямому HTTP API для полного контроля над валидацией данных.

### Что изменено

1. **Удалена зависимость от SDK** - вместо `DeepgramClient` используется `httpx.AsyncClient`
2. **Прямые HTTP запросы** - отправка запросов напрямую в `https://api.deepgram.com/v1/listen`
3. **Работа с сырым JSON** - обработка ответов как словарей без Pydantic валидации
4. **Сохранена вся функциональность** - диаризация, параметры языка, форматирование

### Преимущества нового подхода

✅ **Нет ошибок валидации** - работа с сырыми данными JSON
✅ **Полный контроль** - возможность обрабатывать любые поля из ответа
✅ **Гибкость** - не зависим от версии SDK и его моделей
✅ **Совместимость** - работает с любой версией API
✅ **SSL настройки** - поддержка отключения проверки SSL через `settings.ssl_verify`

### Изменения в коде

#### До (с SDK):
```python
from deepgram import DeepgramClient

self.client = DeepgramClient(api_key=settings.deepgram_api_key)
response = self.client.listen.v1.media.transcribe_file(
    request=buffer_data,
    model=settings.deepgram_model,
    ...
)
```

#### После (прямой HTTP API):
```python
import httpx

self.http_client = httpx.AsyncClient(
    timeout=300.0,
    verify=settings.ssl_verify,
    headers={"Authorization": f"Token {self.api_key}"}
)

response = await self.http_client.post(
    "https://api.deepgram.com/v1/listen",
    params={...},
    content=audio_data,
    headers={"Content-Type": mime_type}
)
response_data = response.json()
```

### Обработка результатов

Вместо работы с Pydantic объектами, используется прямой доступ к словарю:

```python
# До
transcription_text = channel.alternatives[0].transcript
speaker_id = f"Speaker {utterance.speaker}"

# После
transcription_text = alternatives[0].get("transcript", "")
speaker = utterance.get("speaker", 0)
speaker_id = f"Speaker {speaker}"
```

## API параметры

Поддерживаемые параметры запроса:

- `model` - модель распознавания (nova-2, base, enhanced)
- `language` - язык аудио (ru, en и др.)
- `smart_format` - умное форматирование текста
- `punctuate` - добавление пунктуации
- `utterances` - разбиение на высказывания
- `diarize` - идентификация говорящих

## Обработка ошибок

Сохранена обработка всех типов ошибок HTTP:

- **401** - Неверный API ключ
- **400** - Ошибка в параметрах запроса
- **413** - Файл слишком большой
- **429** - Превышен лимит запросов
- **SSL ошибки** - Рекомендация установить `SSL_VERIFY=false`

## Тестирование

После исправления:

1. ✅ Транскрипция работает без ValidationError
2. ✅ Диаризация работает корректно
3. ✅ Все параметры применяются
4. ✅ Обработка ошибок функционирует

## Миграция

Изменения полностью обратно совместимы:

- ✅ API методов не изменился
- ✅ Возвращаемые типы остались прежними
- ✅ Конфигурация та же
- ✅ Не требуется изменений в коде бота

## Конфигурация

Используемые настройки из `config.py`:

```python
DEEPGRAM_API_KEY=your_api_key_here
DEEPGRAM_MODEL=nova-2
DEEPGRAM_LANGUAGE=ru
SSL_VERIFY=true  # или false для отключения проверки сертификатов
```

## Дополнительные возможности

### Cleanup метод
Добавлен метод для корректного закрытия HTTP соединений:

```python
await deepgram_service.cleanup()
```

### MIME типы
Автоматическое определение MIME типа по расширению файла:

- `.mp3` → `audio/mpeg`
- `.wav` → `audio/wav`
- `.m4a` → `audio/mp4`
- `.ogg` → `audio/ogg`

## Зависимости

Теперь для работы Deepgram требуется только:

- `httpx>=0.27.2` (уже в requirements.txt)
- Deepgram API ключ в настройках

Deepgram SDK больше не является обязательной зависимостью для транскрипции.

## Ссылки

- [Deepgram API Documentation](https://developers.deepgram.com/reference/pre-recorded)
- [Deepgram API Parameters](https://developers.deepgram.com/docs/parameters)
- [httpx Documentation](https://www.python-httpx.org/)

---

**Дата:** 19 октября 2025
**Версия:** 1.0
**Статус:** ✅ Исправлено и протестировано

