# 📚 Индекс документации Soroka

Добро пожаловать в документацию проекта Soroka! Здесь вы найдете всю необходимую информацию для работы с ботом.

## 🚀 Быстрый старт

- **[QUICKSTART.md](QUICKSTART.md)** - Быстрый старт для новых пользователей
- **[README.md](README.md)** - Основная документация проекта
- **[PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)** - Обзор проекта и архитектуры

## 🛠 Установка и развертывание

- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Руководство по развертыванию
- **[DOCKER_GUIDE.md](DOCKER_GUIDE.md)** - Работа с Docker
- **[RUN_WITH_SYSTEMD.md](RUN_WITH_SYSTEMD.md)** - Запуск через systemd
- **[APPLE_SILICON_GUIDE.md](APPLE_SILICON_GUIDE.md)** - Установка на Apple Silicon

## 🎙 Транскрипция и диаризация

- **[CLOUD_TRANSCRIPTION_GUIDE.md](CLOUD_TRANSCRIPTION_GUIDE.md)** - Облачная транскрипция
- **[SPEECHMATICS_INTEGRATION.md](SPEECHMATICS_INTEGRATION.md)** - Интеграция Speechmatics API
- **[PICOVOICE_INTEGRATION.md](PICOVOICE_INTEGRATION.md)** - Интеграция Picovoice
- **[PICOVOICE_QUICKSTART.md](PICOVOICE_QUICKSTART.md)** - Быстрый старт с Picovoice
- **[HYBRID_PICOVOICE_EXPLANATION.md](HYBRID_PICOVOICE_EXPLANATION.md)** - Гибридный подход с Picovoice

## 🔧 Производительность и оптимизация

- **[PERFORMANCE_OPTIMIZATION.md](PERFORMANCE_OPTIMIZATION.md)** - Оптимизация производительности
- **[OOM_PROTECTION_GUIDE.md](OOM_PROTECTION_GUIDE.md)** - Защита от нехватки памяти
- **[PROGRESS_OPTIMIZATION.md](PROGRESS_OPTIMIZATION.md)** - Оптимизация прогресса
  
Примечание: материалы по асинхронной оптимизации теперь входят в руководство по производительности.

## 🛡 Надежность и стабильность

- **[RELIABILITY_GUIDE.md](RELIABILITY_GUIDE.md)** - Руководство по надежности
- **[HEALTH_CHECK_LLM_FIX.md](HEALTH_CHECK_LLM_FIX.md)** - Проверка здоровья LLM
- **[FLOOD_CONTROL_FIX.md](FLOOD_CONTROL_FIX.md)** - 🆕 Исправление Flood Control и Error Handler (октябрь 2025)
- **[FLOOD_CONTROL_QUICKSTART.md](FLOOD_CONTROL_QUICKSTART.md)** - 🆕 Краткое руководство по Flood Control
  
Примечание: раздел о Circuit Breaker включен в руководство по надежности.

## 🎨 Пользовательский интерфейс

- **[UX_IMPROVEMENTS.md](UX_IMPROVEMENTS.md)** - Улучшения UX
- **[MESSAGE_LENGTH_FIX.md](MESSAGE_LENGTH_FIX.md)** - Исправление длины сообщений
- **[PROGRESS_TRACKING.md](PROGRESS_TRACKING.md)** - Отслеживание прогресса

## 🔗 Интеграции

- **[URL_SUPPORT.md](URL_SUPPORT.md)** - Поддержка URL
- **[LLM_TEMPLATE_IMPROVEMENTS.md](LLM_TEMPLATE_IMPROVEMENTS.md)** - Улучшения LLM и шаблонов
- **[LLM_PROMPT_IMPROVEMENTS.md](LLM_PROMPT_IMPROVEMENTS.md)** - 🆕 Улучшения промптов для LLM (октябрь 2025)

## 🐛 Исправления и обновления

### Критические исправления
- **[CRITICAL_FIXES.md](CRITICAL_FIXES.md)** - Критические исправления
- **[OOM_FIX_SUMMARY.md](OOM_FIX_SUMMARY.md)** - Исправления OOM
- **[SSL_TROUBLESHOOTING.md](SSL_TROUBLESHOOTING.md)** - Решение SSL проблем

### Специфичные исправления
- **[DIARIZATION_WARNINGS_FIX.md](DIARIZATION_WARNINGS_FIX.md)** - Исправление предупреждений диаризации
- **[EVENT_LOOP_FIX.md](EVENT_LOOP_FIX.md)** - Исправление event loop
- **[FILE_SIZE_LIMITS_FIX.md](FILE_SIZE_LIMITS_FIX.md)** - Исправление лимитов файлов
- **[JSON_SERIALIZATION_FIX.md](JSON_SERIALIZATION_FIX.md)** - Исправление JSON сериализации
- **[SHUTDOWN_ERRORS_FIX.md](SHUTDOWN_ERRORS_FIX.md)** - Исправление ошибок завершения
- **[URL_FORMAT_FIX.md](URL_FORMAT_FIX.md)** - Исправление формата URL

## 📊 Отчеты и сводки

- **[PROJECT_COMPLETION.md](PROJECT_COMPLETION.md)** - Завершение проекта
- **[COMPLETE_IMPROVEMENTS_SUMMARY.md](COMPLETE_IMPROVEMENTS_SUMMARY.md)** - Полная сводка улучшений
- **[PROGRESS_OPTIMIZATION_SUMMARY.md](PROGRESS_OPTIMIZATION_SUMMARY.md)** - Сводка оптимизации прогресса
- **[PICOVOICE_CHANGES_SUMMARY.md](PICOVOICE_CHANGES_SUMMARY.md)** - Сводка изменений Picovoice

## 🔄 Рефакторинг

- **[REFACTORING_GUIDE.md](REFACTORING_GUIDE.md)** - Руководство по рефакторингу

## 📈 Диаграммы

- **[HYBRID_APPROACH_DIAGRAM.md](HYBRID_APPROACH_DIAGRAM.md)** - Диаграмма гибридного подхода

---

## 🔍 Поиск по документации

Если вы не можете найти нужную информацию, попробуйте:

1. **Поиск по ключевым словам** в файлах документации
2. **Проверьте раздел "Исправления"** - возможно, ваша проблема уже решена
3. **Обратитесь к руководствам по установке** для решения проблем с развертыванием
4. **Изучите раздел "Производительность"** для оптимизации работы

## 📝 Обновления документации

Документация регулярно обновляется. Последние изменения:
- **23 октября 2025**: Исправлен Flood Control и Error Handler
  - Устранены каскадные ошибки при flood control
  - Добавлен превентивный rate limiting для Telegram API
  - Созданы безопасные обертки для всех Telegram операций
  - Исправлена сигнатура error handler для aiogram 3.x
- **4 октября 2025**: Значительные улучшения промптов для LLM
- Добавлена интеграция Speechmatics API
- Исправлены SSL проблемы
- Улучшена документация по производительности
- Добавлены руководства по решению проблем

---

*Для получения актуальной информации всегда обращайтесь к последней версии документации.*
