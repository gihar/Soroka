# Design: Admin-only выбор модели ИИ

**Дата:** 2026-05-21
**Скоуп:** Перенос выбора модели обработки из пользовательских настроек в глобальную админскую настройку, удаление multi-provider слоя.
**Предшественник:** `docs/plans/2026-04-03-model-management-design.md` — ввёл `model_presets` и admin-команды `/add_model` / `/models`. Эта спека строится поверх него и меняет семантику выбора с per-user на global admin-only.

---

## 1. Цель и мотивация

Сейчас любой пользователь бота может в `/settings` выбрать провайдера ИИ (OpenAI/Anthropic/Yandex) и конкретный OpenAI-пресет. Это приводит к:

- Несогласованным результатам между пользователями (один и тот же файл обрабатывается разными моделями).
- Невозможности централизованно контролировать стоимость и качество.
- Сложности фоллбэка и кэширования (per-user preference перемешан с per-preset client cache).

Цель: одна активная модель на бота, выбираемая только администратором. Пользователь не управляет выбором модели и провайдера.

---

## 2. Принятые решения

| # | Решение | Обоснование |
|---|---|---|
| D1 | Только модель админ-only, провайдер + модель объединены в одну админскую настройку **«Модель ИИ»** | Упрощение UX, устранение дубликата (preset уже описывает provider implicitly через base_url) |
| D2 | Глобальный выбор — одна `active_model_key` на бота | Запрос пользователя; устраняет per-user кэш |
| D3 | Хранение — новая таблица `app_settings` (key-value) | Расширяемо для будущих глобальных настроек, мигрируется автоматически |
| D4 | Anthropic/Yandex провайдеры удаляются полностью из кода | Запрос пользователя; устраняет fallback-цепочку и неиспользуемый код |
| D5 | Колонки `users.preferred_llm_provider`, `users.preferred_openai_model_key` остаются в БД, не читаются и не пишутся | Безопасная миграция без `ALTER TABLE DROP COLUMN` |
| D6 | Не-админ не видит активную модель ни в /start, ни в /settings | Запрос пользователя; повышает приватность конфигурации |
| D7 | Удаление активного пресета **запрещено** | Защита от состояния «бот без рабочей модели» |
| D8 | Дублирующая кнопка «▶️ Сделать активной» в `/models` | Удобство для админа без переключения меню |

---

## 3. Архитектура

Изменения затрагивают четыре слоя:

- **БД:** новая таблица `app_settings (key, value, updated_at, updated_by)`. Используемый ключ — `active_model_key` (значение — `model_presets.key`).
- **LLM-слой:** `LLMManager` оставляет только `OpenAIProvider`. Файлы `anthropic_provider.py`, `yandex_provider.py` и их тесты удаляются. Метод `generate_protocol_with_fallback(preferred_provider=…)` удаляется.
- **Резолюция модели:** на каждый запрос обработки читается `app_settings.active_model_key` → `model_presets` запись передаётся в `OpenAIProvider` как полный preset (без промежуточной «провайдер-агностичной» абстракции).
- **UI:** `create_settings_menu(is_admin)` собирает кнопки условно. Админ видит дополнительную «🤖 Модель ИИ». Старые «🤖 Предпочитаемый ИИ» и «🧠 Модель OpenAI» удаляются.

---

## 4. Схема БД

### 4.1 Новая таблица `app_settings`

```sql
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_by INTEGER
);
```

`updated_by` — `telegram_id` админа, изменившего значение. `NULL` означает системный seed на старте.

### 4.2 Используемые ключи (первая итерация)

| key | value формат | назначение |
|---|---|---|
| `active_model_key` | `TEXT` — `model_presets.key` | Глобально выбранная админом модель |

### 4.3 Seed при старте

В `init_db`:

1. `CREATE TABLE IF NOT EXISTS app_settings (...)` — идемпотентно.
2. Если `app_settings WHERE key = 'active_model_key'` пусто, выбрать `key` из `model_presets WHERE is_enabled = 1 ORDER BY created_at LIMIT 1` и записать его как `active_model_key` с `updated_by = NULL`.
3. Если в `model_presets` нет ни одной enabled-записи — seed пропускается. Бот стартует, но любая обработка возвращает `AdminConfigurationError` до настройки админом.

### 4.4 Целостность

- `FOREIGN KEY` от `app_settings.value` к `model_presets.key` **не делается** (value — общий TEXT для будущих ключей).
- Валидация на уровне `AppSettingsRepository.set_active_model_key()`: пресет существует и `is_enabled = 1`.
- При попытке `delete` или `disable` активного пресета (через `/models` или репозиторий) — поднимается `ActivePresetDeletionError`, операция отклоняется.

### 4.5 Затронутые существующие таблицы

- `users.preferred_llm_provider` — остаётся, не используется.
- `users.preferred_openai_model_key` — остаётся, не используется.
- `model_presets` — без изменений.

---

## 5. Новый компонент: `AppSettingsRepository`

**Файл:** `src/database/app_settings_repo.py` (новый).

**Публичные методы:**

```python
async def get(key: str) -> Optional[str]
async def set(key: str, value: str, admin_id: Optional[int]) -> None
async def get_active_model_key() -> Optional[str]
async def set_active_model_key(preset_key: str, admin_id: int) -> None  # валидирует preset
```

`set_active_model_key` проверяет: preset существует и `is_enabled = 1`. Если нет — `ValueError`. Преобразуется в alert в callback-хэндлере.

---

## 6. UI

### 6.1 Меню настроек

`create_settings_menu(is_admin: bool) -> InlineKeyboardMarkup` в `src/ux/quick_actions.py`. Все callers передают `is_admin(callback.from_user.id)`.

**Не-админ:**

- 📤 Вывод протокола
- 📝 Шаблон по умолчанию
- 📊 Статистика
- 🔄 Сбросить настройки

**Админ:** то же + сверху:

- 🤖 **Модель ИИ** — `callback_data="settings_active_model"`

Удаляются для всех: «🤖 Предпочитаемый ИИ», «🧠 Модель OpenAI».

### 6.2 Новые callback-хэндлеры

**`settings_active_model` (admin-only):**

1. Проверка `is_admin(callback.from_user.id)`. Не-админ → alert «❌ Доступно только администратору», лог уровня `warning`.
2. `preset_repo.get_enabled()` — список доступных пресетов.
3. Если пусто — сообщение «❌ Нет моделей. Используй `/add_model`» + «⬅️ Назад».
4. Рендер списка пресетов. Рядом с активным (по `app_settings_repo.get_active_model_key()`) — `✅`.
5. callback_data на пресет: `set_active_model_<key>`.

**`set_active_model_<key>` (admin-only):**

1. `is_admin` check.
2. `app_settings_repo.set_active_model_key(key, admin_id)` — валидирует и UPSERT-ит.
3. Сообщение об успехе с именем модели + «⬅️ Назад к настройкам».
4. `INFO`-лог: `active_model_key set to '{key}' by admin {admin_id}`.

### 6.3 Удаляемые callback-хэндлеры

В `src/handlers/callbacks/settings_callbacks.py`:

- `settings_preferred_llm_callback`
- `settings_openai_model_callback`
- `set_openai_model_callback` (старый, per-user)
- `reset_openai_model_preference_callback`

В `src/handlers/callbacks/llm_callbacks.py` — все `set_llm_*`, `reset_llm_preference`. Если файл становится пустым — удаляется.

В `settings_reset_callback` убирается вызов `update_user_llm_preference(..., None)`.

### 6.4 `/start` и заголовок настроек

В `src/handlers/command_handlers.py`:

- Строка `f"Модель OpenAI: {openai_model_name}\n\n"` — для **не-админа** убирается полностью.
- Для **админа** строка становится `f"Модель: {active_model_name}\n\n"`, где `active_model_name` резолвится через `app_settings_repo` → `model_presets.name`.

Аналогично — в тексте, который рендерится в `back_to_settings_callback` (если там есть упоминание модели).

### 6.5 `/models` (admin-команда, уже существует)

Дополнения:

- В списке пресетов рядом с активным — `✅`.
- В карточке пресета — кнопка «▶️ Сделать активной» (вызывает тот же `set_active_model_<key>` callback).
- При попытке удалить или disable активный пресет — `ActivePresetDeletionError`, пользователю сообщение: «❌ Нельзя удалить активную модель. Сначала выбери другую в /settings → Модель ИИ».

---

## 7. Резолвинг модели при обработке

### 7.1 Новый flow

В processing-сервисе (`src/services/enhanced_llm_service.py` или `processing_service.py` — место определит план), где сейчас вызывается `generate_protocol_with_fallback`:

```python
active_key = await app_settings_repo.get_active_model_key()
if not active_key:
    raise AdminConfigurationError("Модель не настроена")
preset = await preset_repo.get_by_key(active_key)
if not preset or not preset["is_enabled"]:
    raise AdminConfigurationError("Активная модель недоступна")
result = await llm_manager.generate_protocol(
    preset=preset,
    transcription=...,
    template_variables=...,
    diarization_data=...,
)
```

Модель резолвится на каждый запрос (один SELECT по PK). Без кэша на стороне service.

### 7.2 Изменения `LLMManager`

**Файл:** `src/llm/manager.py`.

- `self.providers = {"openai": OpenAIProvider()}` (Anthropic/Yandex удалены).
- `get_available_providers()` — удалён (callers исчезают вместе с UI выбора провайдера).
- `generate_protocol_with_fallback(preferred_provider=…)` — удалён.
- Новый/изменённый: `async def generate_protocol(preset: dict, transcription, template_variables, diarization_data, **kwargs)`. Внутри — прямой вызов `OpenAIProvider.generate_protocol(preset=…, ...)`.

### 7.3 Изменения `OpenAIProvider`

**Файл:** `src/llm/providers/openai_provider.py`.

- Уже принимает preset через per-preset client cache (коммит `d0dcf49`). Подтвердить при имплементации.
- `is_available()` — возвращает `True`, если есть хотя бы один enabled preset. (Опциональная доп. проверка `api_key` у активного — в первой итерации не делаем.)
- Метод инвалидации кэша при upsert пресета: `invalidate_cache(key: str)`. Вызывается из `ModelPresetRepository.upsert()` после изменений.

### 7.4 Удаляемые файлы

- `src/llm/providers/anthropic_provider.py`
- `src/llm/providers/yandex_provider.py`
- Все их тесты (`tests/llm/test_anthropic*.py`, `tests/llm/test_yandex*.py` — перепроверить Glob в плане).

---

## 8. Обработка ошибок

### 8.1 Новые классы исключений

**Файл:** `src/exceptions/configuration.py` (новый, по паттерну существующих `processing.py`/`user.py`/etc.). Реэкспорт из `src/exceptions/__init__.py`.

```python
from src.exceptions.base import BotException

class AdminConfigurationError(BotException):
    """Operation cannot proceed because admin-configured state is missing or invalid."""

class ActivePresetDeletionError(BotException):
    """Attempt to delete or disable a preset that is currently the active model."""
```

Оба наследуют `BotException` — следуют существующему паттерну проекта.

### 8.2 Сценарии и тексты

| Условие | Внутреннее поведение | Пользователю |
|---|---|---|
| `active_model_key` пуст в БД | `AdminConfigurationError` | «❌ Бот ещё не настроен администратором. Попробуйте позже.» |
| Активный preset исчез или `is_enabled = 0` | `AdminConfigurationError` | «❌ Активная модель временно недоступна. Обратитесь к администратору.» |
| Не-админ дёргает админ-callback | Лог `warning` + alert | «❌ Доступно только администратору» |
| Удаление/disable активного пресета | `ActivePresetDeletionError` | «❌ Нельзя удалить/отключить активную модель. Сначала выбери другую в /settings → Модель ИИ» |
| Старая кнопка из закешированного сообщения | aiogram дефолт + `safe_edit_text` | «❌ Действие устарело» |

Все ошибки логируются с контекстом `telegram_id` и (если применимо) `active_model_key`.

---

## 9. Миграция и развёртывание

### 9.1 БД

- При старте бота — `CREATE TABLE IF NOT EXISTS app_settings`, затем seed `active_model_key`. Идемпотентно.
- `users.preferred_*` колонки не трогаем.
- Откат: код возвращается из git, таблица `app_settings` остаётся (не мешает старому коду).

### 9.2 Конфиг

- Из `.env`, `env_example` и `src/config.py` удаляются:
  - `ANTHROPIC_API_KEY`
  - `YANDEX_API_KEY`, `YANDEX_FOLDER_ID` и связанные
- `OPENAI_API_KEY` и связанные `OPENAI_*` остаются как fallback для пресетов без явного ключа.

### 9.3 Релиз

Один процесс, один рестарт. Никакой rolling-логики. После рестарта админ заходит в `/settings → 🤖 Модель ИИ` и при необходимости меняет модель.

---

## 10. Безопасность

- Авторизация выбора модели — двухуровневая: (a) кнопка скрыта в UI для не-админа, (b) `is_admin` check внутри каждого admin-callback. Защита от forged callback_data.
- `api_key` пресетов — текущее маскирование в логах сохраняется без изменений (верифицировать на ревью).
- `/add_model`, `/models` — admin guard уже стоит, переиспользуется.

---

## 11. Тестирование

Покрытие 80%+ по правилу `~/.claude/rules/testing.md`. Пирамида: unit → integration → (optional) E2E.

### 11.1 Unit

**`AppSettingsRepository`:**

- `get` возвращает `None` для отсутствующего ключа.
- `set` делает UPSERT, обновляет `updated_at` и `updated_by`.
- `set_active_model_key` отклоняет несуществующий preset.
- `set_active_model_key` отклоняет disabled preset.
- `set_active_model_key` UPSERT-ит для валидного preset.

**`ModelPresetRepository` (новые проверки):**

- `delete(key)`, где `key == active_model_key` → `ActivePresetDeletionError`.
- `disable(key)`, где `key == active_model_key` → `ActivePresetDeletionError`.
- `delete(key)` для неактивного — успешно.

**`LLMManager.generate_protocol(preset=…)`:**

- Передаёт `model`, `base_url`, `api_key` в `OpenAIProvider`.
- Пропагирует ошибки провайдера наружу.

**Резолюция в processing-сервисе:**

- Пустой `active_model_key` → `AdminConfigurationError`.
- Активный preset disabled → `AdminConfigurationError`.
- Happy path: preset резолвится и передаётся.

### 11.2 Integration

**Settings menu rendering:**

- `create_settings_menu(is_admin=True)` содержит `settings_active_model`.
- `create_settings_menu(is_admin=False)` НЕ содержит `settings_active_model`, `settings_preferred_llm`, `settings_openai_model`.

**Callback `settings_active_model`:**

- Админ → видит список пресетов с ✅ напротив активного.
- Не-админ → alert, БД не меняется.

**Callback `set_active_model_<key>`:**

- Админ выбирает enabled preset → `active_model_key` обновляется.
- Админ выбирает несуществующий key → alert, БД не меняется.
- Не-админ → alert, БД не меняется.

**`/start` строка про модель:**

- Админ → «Модель: …» присутствует.
- Не-админ → строки нет.

### 11.3 Миграционные

- Пустая БД → `init_db` создаёт таблицу, seed пропущен.
- БД с пресетами, без `app_settings` → seed работает, выбран первый enabled preset.
- БД с уже выбранным `active_model_key` → seed НЕ перезаписывает.
- БД с `users.preferred_openai_model_key` → значения нетронуты.

### 11.4 Регрессии (grep-проверки на этапе ревью)

- 0 вхождений `user.preferred_openai_model_key` в коде после рефакторинга.
- 0 вхождений `generate_protocol_with_fallback`.
- 0 импортов `AnthropicProvider`, `YandexGPTProvider`.

---

## 12. Скоуп вне этой спеки

Следующие пункты намеренно не делаются в этой итерации:

- Опциональный `.env` override (`ACTIVE_MODEL_KEY=…`) для seed — YAGNI до первой потребности.
- Per-chat / per-template модели — выходит за рамки задачи.
- Восстановление multi-provider слоя в UI — не востребовано.
- ALTER TABLE DROP COLUMN для `users.preferred_*` — будет сделано отдельной миграцией, если потребуется.

---

## 13. Файлы, которые планируется тронуть

**Новые:**

- `src/database/app_settings_repo.py`
- `src/database/migrations/` (если используется отдельная папка миграций — иначе блок в `database.py`)
- Тесты для `AppSettingsRepository`, удаления активного пресета, нового callback.

**Изменяемые:**

- `src/database/database.py` — `init_db` создаёт `app_settings` и сидит `active_model_key`.
- `src/database/model_preset_repo.py` — guard на удаление/disable активного пресета.
- `src/ux/quick_actions.py` — `create_settings_menu(is_admin)`.
- `src/handlers/callbacks/settings_callbacks.py` — новые callbacks, удаление старых.
- `src/handlers/callbacks/llm_callbacks.py` — удаление провайдерных callbacks (возможно весь файл).
- `src/handlers/admin_handlers.py` — кнопка «▶️ Сделать активной» в карточке пресета, guard на удаление активного.
- `src/handlers/command_handlers.py` — `/start` строка про модель.
- `src/handlers/message_handlers.py` — резолвинг модели при обработке (убрать чтение `preferred_*`).
- `src/services/user_service.py` — удалить `update_user_llm_preference`, `update_user_openai_model_preference`.
- `src/services/enhanced_llm_service.py` — резолвинг модели через `app_settings_repo`.
- `src/llm/manager.py` — только OpenAI, новый `generate_protocol(preset=…)`.
- `src/llm/providers/openai_provider.py` — метод `invalidate_cache(key)` (если ещё нет).
- `src/exceptions/__init__.py` — реэкспорт новых классов.
- `src/exceptions/configuration.py` — новый файл с `AdminConfigurationError`, `ActivePresetDeletionError`.
- `src/config.py` — удалить Anthropic/Yandex поля.
- `.env`, `env_example` — удалить Anthropic/Yandex переменные.

**Удаляемые:**

- `src/llm/providers/anthropic_provider.py`
- `src/llm/providers/yandex_provider.py`
- Их тесты.
