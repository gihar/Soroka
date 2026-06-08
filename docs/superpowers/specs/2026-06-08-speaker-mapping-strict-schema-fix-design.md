# Восстановление UI сопоставления спикеров с участниками

**Дата:** 2026-06-08
**Статус:** Дизайн утверждён, ожидает ревью спеки
**Тип:** Исправление продакшен-регрессии

## Проблема

После недавних изменений исчезла функциональность, при которой пользователь
сопоставлял спикеров (из диаризации) с участниками встречи: сообщение с
кнопками подтверждения сопоставления **вообще перестало появляться**. Протокол
генерируется сразу, без шага «проверьте сопоставление».

Симптом подтверждён пользователем: «Сообщение с кнопками вообще не появляется».

## Корневая причина (подтверждена на проде)

Прод (`/home/jimmy/Soroka`, `soroka.service`) работает на коммите `a72e942`,
провайдер LLM — OpenRouter → `openai/gpt-5-mini` (строгий Structured Outputs).
Флаги в рантайме процесса включены: `ENABLE_SPEAKER_MAPPING=true`,
`ENABLE_SPEAKER_MAPPING_CONFIRMATION=true`, `ENABLE_DIARIZATION=true`.

Цепочка отказа (из логов journald прода, 2026-06-06):

1. PR #13 («admin-only-model», убран выбор LLM пользователем) → все запросы
   пошли в единый активный пресет `openai/gpt-5-mini` со **строгим**
   structured outputs.
2. `SpeakerMappingSchema` — **единственная** из 8+ схем в
   `src/models/llm_schemas.py` без `class Config: extra = "forbid"`
   (в git его не было никогда).
3. Без `extra="forbid"` Pydantic не ставит `additionalProperties: false` в
   корень схемы, но `get_json_schema` всё равно отправляет `strict: True`.
4. OpenAI отклоняет запрос:
   `400 — Invalid schema for response_format 'SpeakerMappingSchema':
   In context=(), 'additionalProperties' is required to be supplied and to be false`
   (`context=()` = корень схемы).
5. `_call_llm_for_mapping` ловит исключение и **молча** возвращает `{}`
   (`speaker_mapping_service.py:600-602`).
6. `_run_speaker_mapping` → `({}, None)`; в `_process_file_optimized` условие
   `if speaker_mapping:` ложно → ветка `enable_speaker_mapping_confirmation`
   **полностью пропускается** (`processing/processing_service.py:391-405`).
7. **UI сопоставления никогда не показывается.** Протокол генерируется без него.

Эмпирическое подтверждение на проде (venv):

```
SPEAKER_MAPPING_SCHEMA:  root additionalProperties = <<MISSING>>  | strict=True   ← БАГ
PROTOCOL_SCHEMA:         root additionalProperties = False        | strict=True   ← OK
MEETING_ANALYSIS_SCHEMA: root additionalProperties = False        | strict=True   ← OK
```

Это **не** регрессия паузы/resume из рефакторинга #15. Это сломанный LLM-вызов
сопоставления, замаскированный под «никого не удалось сопоставить» из-за двойного
молчаливого проглатывания ошибки.

## Выбранный подход: C (схема + защита генератора + громкий сбой)

Рассмотренные альтернативы:

- **A — минимальный**: только `extra="forbid"` в `SpeakerMappingSchema`.
  Возвращает фичу одной строкой, но не защищает от повтора и оставляет
  молчаливый сбой.
- **B — A + защита `get_json_schema`**: централизует контракт strict для всех
  схем. Закрывает весь класс багов.
- **C — B + громкий сбой** *(выбран)*: дополнительно делает жёсткий сбой
  LLM-вызова видимым в логах/мониторинге, чтобы будущий обрыв провайдера/схемы
  не выключал фичу незаметно.

## Детальный дизайн

### Часть 1 — Фикс схемы (сам баг)

**Файл:** `src/models/llm_schemas.py`, класс `SpeakerMappingSchema` (~строка 100).

Добавить `class Config: extra = "forbid"` — единообразно со всеми остальными
схемами (`ProtocolSchema`, `MeetingAnalysisSchema`, `ProtocolDataSchema`,
`UnifiedProtocolSchema`, `ODProtocolSchema`, `TwoStage*`, `SelfReflectionSchema`).
В результате Pydantic эмитит `additionalProperties: false` в корне схемы, и
строгий режим OpenAI принимает `response_format`.

Доказательство достаточности (транзитивно): `PROTOCOL_SCHEMA` с тем же
провайдером и с Dict-полями (`detected_speaker_mapping: Optional[Dict[str,str]]`
и др.) уже работает в проде — значит провайдер принимает типизированные
`additionalProperties` у вложенных Dict, и единственное, чего не хватает
`SpeakerMappingSchema`, — `additionalProperties:false` в корне.

### Часть 2 — Защита генератора (весь класс багов)

**Файл:** `src/models/llm_schemas.py`, функция `get_json_schema`.

Добавить отдельный проход `enforce_additional_properties_false(schema_dict)`,
выполняемый после `fix_required_fields`, перед формированием итогового словаря:

- Рекурсивный обход узлов: сам узел, его `properties.*`, `items`, `$defs.*`.
- Правило: если узел — объект (`type == "object"` или есть ключ `properties`)
  **и** в нём **отсутствует** ключ `additionalProperties` → проставить
  `additionalProperties = false`.
- **Не трогать** узлы, где `additionalProperties` уже задан (это типизированные
  Dict-карты вида `{type: string}` — провайдер их принимает; перезапись на
  `false` сломала бы динамические ключи `speaker_mappings`/`confidence_scores`).

Это превращает `get_json_schema` в единственную точку соблюдения контракта
strict: ни одна будущая схема не уедет в прод с `strict:true`, но без
`additionalProperties:false`.

Требование иммутабельности из стиля проекта: проход модифицирует словарь,
полученный из `model_json_schema()` (свежая копия на каждый вызов), а не общий
разделяемый объект — поэтому побочных эффектов на чужие данные нет. Существующий
`fix_required_fields` уже мутирует тот же локальный словарь in-place; новый проход
следует тому же ограниченному паттерну в пределах функции.

### Часть 3 — Громкий сбой вместо молчаливого `{}`

**Файл:** `src/services/speaker_mapping_service.py`.

- Ввести типизированное исключение `SpeakerMappingLLMError` (наследник
  `Exception`) в модуле сервиса.
- `_call_llm_for_mapping`: на ошибке вызова API/схемы (текущий `except` на
  строке ~600) — **поднимать** `SpeakerMappingLLMError(...)` вместо `return {}`.
  Так «жёсткий сбой» становится отличим от «успешного, но пустого результата»
  (когда LLM честно вернул пустой mapping).
- `map_speakers_to_participants`: добавить **отдельную** ветку
  `except SpeakerMappingLLMError`:
  - логировать на уровне **ERROR** с явным грепаемым маркером
    `SPEAKER_MAPPING_LLM_FAILED` (включая провайдера и краткую причину);
  - **деградировать мягко** — вернуть `({}, "general")`, чтобы генерация
    протокола продолжилась (фича не должна валить весь пайплайн);
  - опционально инкрементировать счётчик в `src/performance/metrics.py`, если
    там есть простой хук (решается на этапе плана; не обязательно).
- Существующий общий `except Exception` остаётся как «последний рубеж», но
  жёсткие сбои LLM теперь идут через явную ветку и не сливаются с обычным
  пустым результатом.

Это устраняет молчаливое проглатывание (требование стиля: «никогда молча не
глотать ошибки»), сохраняя устойчивость пайплайна.

## Тесты (TDD: красный → зелёный)

`tests/` (Python, pytest):

1. `SPEAKER_MAPPING_SCHEMA["schema"].get("additionalProperties") is False` и
   `SPEAKER_MAPPING_SCHEMA["strict"] is True`.
2. **Параметризованный гард для всех схем**: для каждого предопределённого
   `*_SCHEMA` (PROTOCOL, TWO_STAGE_*, UNIFIED, SPEAKER_MAPPING, OD, MEETING_*,
   PROTOCOL_DATA, …) — если `strict is True`, то корень имеет
   `additionalProperties is False`. Ловит будущие регрессии.
3. `get_json_schema` **не затирает** типизированный `additionalProperties` у
   Dict-полей: в `SPEAKER_MAPPING_SCHEMA` узлы `speaker_mappings` и
   `confidence_scores` сохраняют `additionalProperties` вида `{type: ...}`,
   а не `false`.
4. Часть 3: при выбросе ошибки из `_call_llm_for_mapping` (замоканный вызов
   LLM, поднимающий исключение) `map_speakers_to_participants` логирует маркер
   `SPEAKER_MAPPING_LLM_FAILED` и возвращает `({}, "general")` без падения.

Цель покрытия — по правилам проекта (80%+) для затронутых функций.

## Проверка и деплой

- **Локально:** повторно сгенерировать схемы — корень `SPEAKER_MAPPING_SCHEMA`
  должен стать `additionalProperties: False`; `ruff` чистый; все тесты зелёные.
- **Прод:** после мержа в `main` — `git pull` + `systemctl restart
  soroka.service`. Затем реальный прогон файла с диаризацией и списком
  участников → в журнале должна появиться ветка
  «UI подтверждения сопоставления включён …» и **сообщение с кнопками**;
  ошибки `400 Invalid schema ... SpeakerMappingSchema` исчезают.
- Рестарт прода — отдельное подтверждение пользователя перед выполнением
  (внешнее, необратимое действие).

## Вне области (out of scope)

- Поведение паузы/resume из рефакторинга #15 — не меняется (оно исправно).
- Логика самого сопоставления (`_validate_mapping`, построение промпта) — без
  изменений.
- Выбор LLM-провайдера/пресета (PR #13) — оставляем как есть; чиним совместимость
  схемы, а не возвращаем выбор модели.

## Риски

- Малый риск: после фикса корня появится новая strict-ошибка по вложенным
  Dict-полям. Считается маловероятным, т.к. `PROTOCOL_SCHEMA` с такими же
  Dict-полями уже работает на том же провайдере. Снимается реальным прогоном на
  проде в шаге проверки.
- Проход `enforce_additional_properties_false` должен корректно отличать
  Dict-карты (типизированный `additionalProperties`) от обычных объектов —
  покрыто тестом №3.
