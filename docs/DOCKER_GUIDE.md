# Docker Guide - Руководство по Docker

## Обзор

Это руководство поможет вам запустить Telegram бота в Docker контейнере. Docker обеспечивает изолированную среду для запуска приложения, что упрощает развертывание и управление.

## Предварительные требования

1. **Docker** - установите Docker Desktop или Docker Engine
   - [Docker Desktop для macOS/Windows](https://docs.docker.com/desktop/)
   - [Docker Engine для Linux](https://docs.docker.com/engine/install/)

2. **Docker Compose** - обычно входит в состав Docker Desktop
   - Для Linux может потребоваться отдельная установка

## Быстрый старт

### 1. Подготовка окружения

```bash
# Клонируйте репозиторий (если еще не сделали)
git clone <your-repo-url>
cd Soroka

# Скопируйте файл с переменными окружения
cp env_example .env

# Отредактируйте .env файл с вашими настройками
nano .env  # или любой текстовый редактор
```

### 2. Настройка переменных окружения

Откройте файл `.env` и установите необходимые значения:

```env
# ОБЯЗАТЕЛЬНО - токен вашего Telegram бота
TELEGRAM_TOKEN=your_actual_telegram_bot_token

# Опционально - API ключи для LLM провайдеров
OPENAI_API_KEY=your_openai_api_key
ANTHROPIC_API_KEY=your_anthropic_api_key
YANDEX_API_KEY=your_yandex_api_key
```

### 3. Запуск контейнера

```bash
# Используйте автоматический скрипт
chmod +x docker-run.sh
./docker-run.sh

# Или запустите вручную
docker-compose up --build -d
```

## Управление контейнером

### Основные команды

```bash
# Запуск в фоновом режиме
docker-compose up -d

# Запуск с пересборкой образа
docker-compose up --build -d

# Просмотр логов
docker-compose logs -f

# Остановка контейнера
docker-compose down

# Перезапуск
docker-compose restart

# Проверка статуса
docker-compose ps
```

### Просмотр логов

```bash
# Все логи
docker-compose logs

# Логи в реальном времени
docker-compose logs -f

# Логи последних 100 строк
docker-compose logs --tail=100
```

## Структура файлов

```
Soroka/
├── Dockerfile              # Конфигурация Docker образа
├── docker-compose.yml      # Конфигурация Docker Compose
├── .dockerignore          # Исключения для Docker
├── docker-run.sh          # Скрипт автоматического запуска
├── .env                   # Переменные окружения (создать из env_example)
├── requirements.txt       # Python зависимости
└── src/                   # Исходный код бота
```

## Монтирование томов

Docker Compose автоматически монтирует следующие директории:

- `./data` → `/app/data` - персистентные данные
- `./logs` → `/app/logs` - логи приложения
- `./temp` → `/app/temp` - временные файлы
- `./cache` → `/app/cache` - кэш
- `bot-db` (volume) → `/app/bot.db` - база данных

## Переменные окружения

### Обязательные

- `TELEGRAM_TOKEN` - токен вашего Telegram бота

### Опциональные

#### LLM Провайдеры
- `OPENAI_API_KEY` - API ключ OpenAI
- `ANTHROPIC_API_KEY` - API ключ Anthropic
- `YANDEX_API_KEY` - API ключ Yandex GPT
- `YANDEX_FOLDER_ID` - ID папки Yandex Cloud

#### Транскрипция
- `GROQ_API_KEY` - API ключ Groq для облачной транскрипции
- `TRANSCRIPTION_MODE` - режим транскрипции (local/cloud/hybrid)

#### Диаризация
- `ENABLE_DIARIZATION` - включить диаризацию (true/false)
- `HUGGINGFACE_TOKEN` - токен Hugging Face
- `PICOVOICE_ACCESS_KEY` - ключ доступа Picovoice

## Устранение неполадок

### Контейнер не запускается

1. Проверьте логи:
   ```bash
   docker-compose logs
   ```

2. Убедитесь, что установлен TELEGRAM_TOKEN в .env файле

3. Проверьте, что порт 8080 не занят другими приложениями

### Проблемы с зависимостями

1. Пересоберите образ:
   ```bash
   docker-compose build --no-cache
   docker-compose up -d
   ```

### Проблемы с правами доступа

1. Проверьте права на директории:
   ```bash
   sudo chown -R $USER:$USER data logs temp cache
   ```

### Проблемы с памятью

Если контейнер потребляет много памяти:

1. Ограничьте ресурсы в docker-compose.yml:
   ```yaml
   services:
     telegram-bot:
       # ... другие настройки ...
       deploy:
         resources:
           limits:
             memory: 2G
             cpus: '1.0'
   ```

## Производительность

### Оптимизация размера образа

- Используется `python:3.11-slim` вместо полного образа
- Многоэтапная сборка для уменьшения размера
- Исключение ненужных файлов через .dockerignore

### Мониторинг ресурсов

```bash
# Просмотр использования ресурсов
docker stats telegram-bot

# Просмотр процессов в контейнере
docker exec -it telegram-bot ps aux
```

## Безопасность

### Рекомендации

1. **Никогда не коммитьте .env файл** в Git
2. Используйте секреты Docker для продакшена
3. Регулярно обновляйте базовый образ Python
4. Ограничивайте права доступа контейнера

### Продакшен настройки

Для продакшена рекомендуется:

1. Использовать Docker secrets вместо переменных окружения
2. Настроить HTTPS для веб-хуков
3. Ограничить ресурсы контейнера
4. Настроить мониторинг и алерты

## Обновление

### Обновление кода

```bash
# Остановите контейнер
docker-compose down

# Получите обновления
git pull

# Пересоберите и запустите
docker-compose up --build -d
```

### Обновление зависимостей

```bash
# Обновите requirements.txt
# Затем пересоберите образ
docker-compose build --no-cache
docker-compose up -d
```

## Поддержка

При возникновении проблем:

1. Проверьте логи: `docker-compose logs -f`
2. Убедитесь в корректности .env файла
3. Проверьте документацию в папке docs/
4. Создайте issue в репозитории проекта
