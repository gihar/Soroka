# Пайплайн обработки встречи (Meeting Processing Pipeline)

Этот документ описывает процесс обработки записи встречи в боте Soroka, от получения файла до генерации финального протокола.

## Схема процесса (Mermaid)

```mermaid
graph TD
    %% Стили
    classDef user fill:#f9f,stroke:#333,stroke-width:2px;
    classDef bot fill:#bbf,stroke:#333,stroke-width:2px;
    classDef process fill:#dfd,stroke:#333,stroke-width:2px;
    classDef db fill:#ff9,stroke:#333,stroke-width:2px;
    classDef external fill:#fdd,stroke:#333,stroke-width:2px;

    %% Узлы
    User((Пользователь)):::user
    
    subgraph Input_Handling [Обработка Входящих]
        MsgHandler[Message Handler]:::bot
        UrlHandler[URL Handler]:::bot
        FileValidation{Валидация}:::process
        ParticipantsMenu[Меню Участников]:::bot
        LLMSelect[Выбор LLM]:::bot
        CreateRequest[Создание ProcessingRequest]:::process
    end

    subgraph Queue_System [Система Очередей]
        QueueManager[TaskQueueManager]:::bot
        DB_Queue[(DB: Queue)]:::db
        Worker[Worker]:::process
        OOM{OOM Check}:::process
    end

    subgraph Processing_Service [OptimizedProcessingService]
        ProcessFile[process_file]:::process
        CacheCheck{Check Cache}:::db
        Download[Скачивание/Подготовка]:::process
        Transcription[Транскрипция]:::process
        Diarization[Диаризация]:::process
        SpeakerMapping[Сопоставление Спикеров]:::process
        MappingConfirm{Подтверждение?}:::user
        TemplateSelect[Выбор Шаблона]:::process
        LLMGen[Генерация LLM]:::external
        Formatting[Форматирование]:::process
        SaveHistory[(DB: History)]:::db
    end

    subgraph Output [Вывод]
        SendResult[Отправка Результата]:::bot
        SplitMsg{Длинное?}:::process
        FileGen[Генерация PDF/MD]:::process
    end

    %% Связи
    User -->|Файл| MsgHandler
    User -->|Ссылка| UrlHandler
    UrlHandler -->|Скачивание| MsgHandler
    MsgHandler --> FileValidation
    FileValidation -- OK --> ParticipantsMenu
    FileValidation -- Ошибка --> User
    ParticipantsMenu -->|Список участников| LLMSelect
    LLMSelect -->|Провайдер| CreateRequest
    CreateRequest --> QueueManager
    
    QueueManager -->|Add| DB_Queue
    QueueManager -->|Assign| Worker
    Worker --> OOM
    OOM -- OK --> ProcessFile
    OOM -- Low Mem --> QueueManager
    
    ProcessFile --> CacheCheck
    CacheCheck -- Hit --> SendResult
    CacheCheck -- Miss --> Download
    Download --> Transcription
    Transcription --> Diarization
    Diarization --> SpeakerMapping
    
    SpeakerMapping --> MappingConfirm
    MappingConfirm -- Нужно подтверждение --> User
    User -- Подтвердил --> ProcessFile
    MappingConfirm -- Авто --> TemplateSelect
    
    TemplateSelect --> LLMGen
    LLMGen --> Formatting
    Formatting --> SaveHistory
    SaveHistory --> SendResult
    
    SendResult --> SplitMsg
    SplitMsg -- Да --> User
    SplitMsg -- Нет --> User
    SendResult -->|Если нужен файл| FileGen
    FileGen --> User
```

## Детальное описание этапов

### 1. Обработка входящих данных (Input Handling)
*   **Точка входа**: `src/handlers/message_handlers.py`
*   **Файлы**: Пользователь отправляет аудио/видео/файл. Бот определяет тип и извлекает `file_id`.
*   **Ссылки**: Пользователь отправляет ссылку (Google Drive/Yandex Disk). Бот скачивает файл во временную директорию.
*   **Валидация**: Проверка размера (до 2GB для Telegram, настройки для внешних) и формата.
*   **Сбор контекста**:
    *   Бот запрашивает список участников через `ParticipantsMenu`.
    *   Бот предлагает выбрать LLM (OpenAI, Anthropic, Yandex) или использует предпочтения пользователя.
*   **Инициализация**: Создается объект `ProcessingRequest` со всеми метаданными (файл, участники, тема, дата).

### 2. Очередь задач (Queue System)
*   **Менеджер**: `src/services/task_queue_manager.py`
*   **Добавление**: Запрос добавляется в `asyncio.Queue` и сохраняется в БД (для надежности при перезапуске).
*   **Воркеры**: Фоновые процессы (`_worker`) разбирают очередь.
*   **Защита ресурсов**: Перед запуском проверяется доступная память (OOM Protection). Если памяти мало, задача возвращается в очередь.
*   **Статус**: Пользователь видит позицию в очереди через `QueueTracker`.

### 3. Обработка (Processing Service)
*   **Ядро**: `src/services/processing/processing_service.py` (класс `ProcessingService`; точка входа `process_file`).
*   **Кеширование**: Вычисляется хеш файла. Если такой файл уже обрабатывался с теми же параметрами, результат возвращается мгновенно из кеша.
*   **Транскрипция**:
    *   Файл конвертируется (если нужно) через `ffmpeg`.
    *   Отправляется в сервис транскрипции (Whisper/Deepgram/etc).
    *   Результат содержит текст и временные метки.
*   **Диаризация**: Разделение текста по спикерам (Speaker 0, Speaker 1...).
*   **Сопоставление спикеров (Speaker Mapping)**:
    *   `src/services/speaker_mapping_service.py` пытается сопоставить "Speaker X" с реальными именами из списка участников, используя LLM.
    *   **UI Подтверждения**: Если включено в настройках, бот присылает пользователю варианты сопоставления. Обработка ставится на паузу (`return None`), а полное состояние сохраняется в `mapping_state_cache` (`request.model_dump()` + `processing_metrics.to_dict()` + `cache_key` + `task_id`). После подтверждения путь возобновления (`continue_processing_after_mapping_confirmation`) восстанавливает состояние и доводит протокол до конца.
*   **Выбор шаблона**: Если шаблон не выбран явно, `SmartTemplateSelector` анализирует транскрипт и предлагает подходящий.
*   **Генерация, форматирование и сборка результата** вынесены в общий метод `_finalize_protocol`, который используется и основным путём, и путём возобновления — поэтому ветки не могут разойтись:
    *   Транскрипт + Шаблон + Метаданные отправляются в LLM (используется `chain-of-thought`).
    *   Ответ LLM очищается, форматируется в Markdown, имена спикеров заменяются на реальные (если есть маппинг).
    *   Собирается `ProcessingResult` с названием активной модели (`LLMGenerationService.resolve_model_display_name`).

### 4. Вывод результата (Output)
*   **Доставка**: Результат отправляется пользователю через общий `src/services/result_sender.py` (`send_result_to_user`) — один и тот же код для обычного потока и для возобновления после подтверждения.
*   **Длинные сообщения**: Если протокол длиннее лимита Telegram, он разбивается на части.
*   **Файлы**: По настройкам пользователя может быть сгенерирован PDF или MD файл.
*   **История**: Результат сохраняется в историю обработок пользователя в БД.
*   **Статус задачи**: При возобновлении исходная задача очереди корректно закрывается (`completed`/`failed`), чтобы строка не зависала в `processing`.
