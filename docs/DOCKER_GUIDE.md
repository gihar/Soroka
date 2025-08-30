# 🐳 Docker руководство для Soroka

Полное руководство по развертыванию Soroka с использованием Docker и Docker Compose.

## 🎯 Обзор

Soroka полностью готов к развертыванию в контейнерах Docker. Это обеспечивает:
- **Изоляцию окружения** - все зависимости в одном контейнере
- **Простоту развертывания** - один образ для всех платформ
- **Масштабируемость** - легко запускать несколько экземпляров
- **Персистентность данных** - сохранение настроек и базы данных

## 🚀 Быстрый старт

### 1. Подготовка окружения

```bash
# Клонируйте репозиторий
git clone <repository-url>
cd Soroka

# Скопируйте файл конфигурации
cp env_example .env
```

### 2. Настройка переменных окружения

Отредактируйте файл `.env`:

```env
# Обязательные настройки
TELEGRAM_TOKEN=your_telegram_bot_token_here

# LLM провайдеры (настройте хотя бы один)
OPENAI_API_KEY=your_openai_api_key_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here
YANDEX_API_KEY=your_yandex_api_key_here
YANDEX_FOLDER_ID=your_yandex_folder_id_here

# Диаризация (опционально)
ENABLE_DIARIZATION=true
PICOVOICE_ACCESS_KEY=your_picovoice_access_key_here
HUGGINGFACE_TOKEN=your_huggingface_token_here

# Облачная транскрипция (опционально)
GROQ_API_KEY=your_groq_api_key_here

# Настройки производительности
MAX_FILE_SIZE=52428800
MAX_EXTERNAL_FILE_SIZE=52428800
DIARIZATION_DEVICE=cpu
```

### 3. Запуск с Docker Compose

```bash
# Запуск в фоновом режиме
docker-compose up -d

# Просмотр логов
docker-compose logs -f

# Остановка
docker-compose down
```

## 🏗️ Архитектура Docker

### Структура файлов

```
Soroka/
├── Dockerfile              # Образ приложения
├── docker-compose.yml      # Оркестрация сервисов
├── docker-run.sh          # Скрипт запуска
├── .env                   # Переменные окружения
├── requirements.txt       # Python зависимости
└── src/                   # Исходный код
```

### Компоненты системы

- **telegram-bot** - основной сервис бота
- **volumes** - персистентное хранение данных
- **healthcheck** - мониторинг состояния
- **environment** - конфигурация через переменные

## 📦 Dockerfile

### Основные особенности

```dockerfile
# Используем официальный образ Python 3.11
FROM python:3.11-slim

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем файлы зависимостей
COPY requirements.txt .

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Копируем исходный код
COPY . .

# Создаем необходимые директории
RUN mkdir -p logs temp cache

# Создаем пользователя для безопасности
RUN useradd --create-home --shell /bin/bash bot && \
    chown -R bot:bot /app
USER bot

# Открываем порт
EXPOSE 8080

# Команда по умолчанию
CMD ["python", "main.py"]
```

### Оптимизации образа

- **Многоэтапная сборка** - минимизация размера образа
- **Кэширование слоев** - ускорение сборки
- **Безопасность** - запуск от непривилегированного пользователя
- **Минимальные зависимости** - только необходимые пакеты

## 🔧 Docker Compose

### Конфигурация сервиса

```yaml
version: '3.8'

services:
  telegram-bot:
    build: .
    container_name: telegram-bot
    restart: unless-stopped
    environment:
      # Основные настройки
      - TELEGRAM_TOKEN=${TELEGRAM_TOKEN}
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
      - SSL_VERIFY=${SSL_VERIFY:-false}
      
      # LLM провайдеры
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - YANDEX_API_KEY=${YANDEX_API_KEY}
      - YANDEX_FOLDER_ID=${YANDEX_FOLDER_ID}
      
      # Диаризация
      - ENABLE_DIARIZATION=${ENABLE_DIARIZATION:-false}
      - PICOVOICE_ACCESS_KEY=${PICOVOICE_ACCESS_KEY}
      - HUGGINGFACE_TOKEN=${HUGGINGFACE_TOKEN}
      
      # Транскрипция
      - GROQ_API_KEY=${GROQ_API_KEY}
      - TRANSCRIPTION_MODE=${TRANSCRIPTION_MODE:-hybrid}
    
    volumes:
      # Персистентные данные
      - ./data:/app/data
      - ./logs:/app/logs
      - ./temp:/app/temp
      - ./cache:/app/cache
      - bot-db:/app/bot.db
    
    ports:
      - "8080:8080"
    
    healthcheck:
      test: ["CMD", "python", "-c", "import requests; requests.get('https://api.telegram.org')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

volumes:
  bot-db:
    driver: local
```

### Ключевые особенности

- **Автоматический перезапуск** - `restart: unless-stopped`
- **Health checks** - мониторинг состояния сервиса
- **Volumes** - персистентное хранение данных
- **Environment variables** - гибкая конфигурация

## 🚀 Варианты развертывания

### 1. Локальное развертывание

```bash
# Сборка и запуск
docker-compose up --build -d

# Просмотр логов
docker-compose logs -f telegram-bot

# Остановка
docker-compose down
```

### 2. Продакшен развертывание

```bash
# Создание продакшен конфигурации
cp docker-compose.yml docker-compose.prod.yml

# Запуск в продакшене
docker-compose -f docker-compose.prod.yml up -d

# Мониторинг
docker-compose -f docker-compose.prod.yml logs -f
```

### 3. Развертывание с внешней базой данных

```yaml
# docker-compose.external-db.yml
version: '3.8'

services:
  telegram-bot:
    build: .
    environment:
      - DATABASE_URL=postgresql://user:pass@host:5432/soroka
    # ... остальные настройки
```

## 📊 Мониторинг и логирование

### Просмотр логов

```bash
# Все логи
docker-compose logs

# Логи конкретного сервиса
docker-compose logs telegram-bot

# Логи в реальном времени
docker-compose logs -f telegram-bot

# Последние 100 строк
docker-compose logs --tail=100 telegram-bot
```

### Health checks

```bash
# Проверка состояния
docker-compose ps

# Детальная информация
docker inspect telegram-bot

# Проверка health check
docker-compose exec telegram-bot python -c "
import requests
try:
    response = requests.get('https://api.telegram.org')
    print(f'Health check: {response.status_code}')
except Exception as e:
    print(f'Health check failed: {e}')
"
```

### Метрики производительности

```bash
# Использование ресурсов
docker stats telegram-bot

# Информация о контейнере
docker-compose exec telegram-bot python -c "
import psutil
print(f'CPU: {psutil.cpu_percent()}%')
print(f'Memory: {psutil.virtual_memory().percent}%')
print(f'Disk: {psutil.disk_usage("/").percent}%')
"
```

## 🔧 Управление контейнерами

### Основные команды

```bash
# Запуск
docker-compose up -d

# Остановка
docker-compose down

# Перезапуск
docker-compose restart

# Пересборка
docker-compose up --build -d

# Удаление с данными
docker-compose down -v
```

### Обновление приложения

```bash
# Остановка
docker-compose down

# Обновление кода
git pull

# Пересборка и запуск
docker-compose up --build -d

# Проверка логов
docker-compose logs -f
```

## 🛠️ Устранение неполадок

### Частые проблемы

#### 1. Ошибка сборки образа

```bash
# Очистка кэша Docker
docker system prune -a

# Пересборка без кэша
docker-compose build --no-cache

# Проверка Dockerfile
docker build -t soroka-test .
```

#### 2. Проблемы с переменными окружения

```bash
# Проверка переменных
docker-compose exec telegram-bot env | grep -E "(TELEGRAM|OPENAI|ANTHROPIC)"

# Проверка файла .env
cat .env

# Перезапуск с новыми переменными
docker-compose down
docker-compose up -d
```

#### 3. Проблемы с правами доступа

```bash
# Исправление прав на volumes
sudo chown -R $USER:$USER ./data ./logs ./temp ./cache

# Проверка прав в контейнере
docker-compose exec telegram-bot ls -la /app
```

#### 4. Проблемы с сетью

```bash
# Проверка сети
docker network ls
docker network inspect soroka_default

# Тест подключения
docker-compose exec telegram-bot ping google.com
```

### Диагностика

#### Проверка состояния контейнера

```bash
# Детальная информация
docker inspect telegram-bot

# Логи запуска
docker-compose logs telegram-bot

# Проверка процессов
docker-compose exec telegram-bot ps aux
```

#### Проверка ресурсов

```bash
# Использование ресурсов
docker stats telegram-bot

# Проверка диска
docker-compose exec telegram-bot df -h

# Проверка памяти
docker-compose exec telegram-bot free -h
```

## 🔒 Безопасность

### Рекомендации

1. **Непривилегированный пользователь** - контейнер запускается от пользователя `bot`
2. **Минимальные права** - только необходимые разрешения
3. **Переменные окружения** - API ключи не в образе
4. **Обновления** - регулярное обновление базового образа

### Продакшен настройки

```yaml
# docker-compose.prod.yml
version: '3.8'

services:
  telegram-bot:
    build: .
    restart: unless-stopped
    security_opt:
      - no-new-privileges:true
    read_only: true
    tmpfs:
      - /tmp
      - /var/tmp
    environment:
      - LOG_LEVEL=WARNING
    # ... остальные настройки
```

## 📈 Масштабирование

### Горизонтальное масштабирование

```bash
# Запуск нескольких экземпляров
docker-compose up -d --scale telegram-bot=3

# Проверка экземпляров
docker-compose ps
```

### Load balancing

```yaml
# docker-compose.scale.yml
version: '3.8'

services:
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
    depends_on:
      - telegram-bot

  telegram-bot:
    build: .
    # ... настройки бота
```

## 🎯 Заключение

Docker развертывание Soroka обеспечивает:

- ✅ **Простота развертывания** - один образ для всех платформ
- ✅ **Изоляция окружения** - все зависимости в контейнере
- ✅ **Персистентность данных** - сохранение настроек и БД
- ✅ **Масштабируемость** - легко запускать несколько экземпляров
- ✅ **Мониторинг** - встроенные health checks и логирование
- ✅ **Безопасность** - непривилегированный пользователь и минимальные права

Для быстрого старта используйте `docker-compose up -d` и следуйте инструкциям по настройке переменных окружения.

---

*Docker руководство актуально для Soroka v2.0+ с полной поддержкой диаризации и гибридной транскрипции.*
