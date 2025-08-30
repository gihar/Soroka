# ⚡ Быстрый старт с Soroka

Полное руководство по быстрой установке и настройке Soroka за 10 минут.

## 🎯 Что такое Soroka?

**Soroka** - это интеллектуальный Telegram бот для автоматического создания протоколов встреч из аудио и видео записей с использованием ИИ.

### 🚀 Ключевые возможности
- **🎯 Диаризация** - автоматическое разделение говорящих
- **🔗 Внешние файлы** - поддержка Google Drive и Яндекс.Диск
- **📦 Гибридная транскрипция** - облачная и локальная обработка
- **🤖 Множественные LLM** - OpenAI, Anthropic, Yandex GPT

## 📋 Предварительные требования

### Системные требования
- **Python 3.11+** (рекомендуется 3.11)
- **8GB RAM** (минимум 4GB для базовой функциональности)
- **2GB свободного места** на диске
- **ffmpeg** (устанавливается автоматически)

### Поддерживаемые платформы
- ✅ **macOS** (Intel и Apple Silicon)
- ✅ **Ubuntu/Debian** (18.04+)
- ✅ **CentOS/RHEL** (7+)
- ✅ **Windows** (WSL2 или Docker)

## 🚀 Установка за 5 минут

### Шаг 1: Клонирование и установка

```bash
# Клонируйте репозиторий
git clone <repository-url>
cd Soroka

# Автоматическая установка (рекомендуется)
chmod +x install.sh
./install.sh
```

### Шаг 2: Настройка конфигурации

```bash
# Скопируйте файл конфигурации
cp env_example .env

# Отредактируйте .env файл
nano .env  # или любой текстовый редактор
```

### Шаг 3: Минимальная конфигурация

Добавьте в `.env` файл **только обязательные** настройки:

```env
# ОБЯЗАТЕЛЬНО
TELEGRAM_TOKEN=your_telegram_bot_token_here

# НАСТРОЙТЕ ХОТЯ БЫ ОДИН LLM ПРОВАЙДЕР
OPENAI_API_KEY=your_openai_api_key_here
# ИЛИ
ANTHROPIC_API_KEY=your_anthropic_api_key_here
# ИЛИ
YANDEX_API_KEY=your_yandex_api_key_here
YANDEX_FOLDER_ID=your_yandex_folder_id_here
```

### Шаг 4: Запуск

```bash
# Запуск бота
python main.py
```

## 🐳 Docker установка (альтернатива)

### Быстрый старт с Docker

```bash
# Клонирование
git clone <repository-url>
cd Soroka

# Настройка
cp env_example .env
# Отредактируйте .env

# Запуск
docker-compose up -d
```

## 🔑 Получение API ключей

### 1. Telegram Bot Token

1. Найдите [@BotFather](https://t.me/botfather) в Telegram
2. Отправьте `/newbot`
3. Следуйте инструкциям
4. Скопируйте токен в `.env`

### 2. OpenAI API (рекомендуется для начала)

1. Зайдите на [platform.openai.com](https://platform.openai.com)
2. Создайте аккаунт
3. Перейдите в [API Keys](https://platform.openai.com/api-keys)
4. Создайте новый ключ
5. Добавьте в `.env`

### 3. Anthropic Claude (альтернатива)

1. Зайдите на [console.anthropic.com](https://console.anthropic.com)
2. Создайте аккаунт
3. Создайте API ключ
4. Добавьте в `.env`

### 4. Yandex GPT (российская альтернатива)

1. Зайдите в [Yandex Cloud Console](https://console.cloud.yandex.ru)
2. Создайте API ключ для Yandex GPT
3. Найдите ID папки в консоли
4. Добавьте в `.env`

## 📱 Первое использование

### 1. Запустите бота

```bash
python main.py
```

### 2. Найдите бота в Telegram

Поищите вашего бота по имени, которое вы указали при создании.

### 3. Отправьте команду `/start`

Бот пришлет приветственное сообщение и инструкции.

### 4. Отправьте аудио/видео файл

- **Аудио**: MP3, WAV, M4A, OGG
- **Видео**: MP4, AVI, MOV, MKV
- **Размер**: до 20MB (через Telegram) или 50MB (внешние ссылки)

### 5. Выберите шаблон и LLM

Бот предложит выбрать:
- **Шаблон протокола** (стандартный, краткий, технический)
- **LLM провайдер** (OpenAI, Anthropic, Yandex)

### 6. Получите результат

Бот создаст структурированный протокол встречи с анализом участников.

## 🎯 Продвинутые настройки

### Включение диаризации

Добавьте в `.env`:

```env
# Диаризация (разделение говорящих)
ENABLE_DIARIZATION=true
HUGGINGFACE_TOKEN=your_huggingface_token_here
```

### Поддержка внешних файлов

Отправьте ссылку на файл в Google Drive или Яндекс.Диск:

```
https://drive.google.com/file/d/YOUR_FILE_ID/view
https://disk.yandex.ru/d/YOUR_FILE_ID
```

### Облачная транскрипция

Добавьте в `.env`:

```env
# Быстрая облачная транскрипция
GROQ_API_KEY=your_groq_api_key_here
TRANSCRIPTION_MODE=hybrid
```

## 🛠️ Устранение неполадок

### Частые проблемы

#### 1. "ffmpeg не найден"

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt-get install ffmpeg

# Или используйте автоматическую установку
./install.sh
```

#### 2. "TELEGRAM_TOKEN не установлен"

Проверьте файл `.env`:
```bash
cat .env | grep TELEGRAM_TOKEN
```

#### 3. "Не установлены API ключи для LLM"

Добавьте хотя бы один API ключ в `.env`:
```env
OPENAI_API_KEY=your_key_here
```

#### 4. SSL ошибки

Добавьте в `.env`:
```env
SSL_VERIFY=false
```

### Проверка установки

```bash
# Проверка Python
python --version

# Проверка ffmpeg
ffmpeg -version

# Проверка зависимостей
pip list | grep -E "(aiogram|openai|anthropic)"

# Проверка конфигурации
python -c "from config import settings; print('Config OK')"
```

## 📊 Мониторинг

### Команды бота для диагностики

- `/help` - справка по командам
- `/performance` - метрики производительности
- `/health` - состояние системы
- `/settings` - текущие настройки

### Логи приложения

```bash
# Просмотр логов
tail -f logs/bot.log

# Поиск ошибок
grep ERROR logs/bot.log
```

## 🎨 Следующие шаги

### 1. Изучите возможности

- **[Полная документация](./README.md)** - все функции системы
- **[Архитектура](./REFACTORING_GUIDE.md)** - как работает система
- **[Производительность](./PERFORMANCE_OPTIMIZATION.md)** - оптимизации

### 2. Настройте диаризацию

- **[Быстрый старт с Picovoice](./PICOVOICE_QUICKSTART.md)** - настройка диаризации
- **[Полная интеграция](./PICOVOICE_INTEGRATION.md)** - детальная настройка

### 3. Развертывание в продакшене

- **[Docker руководство](./DOCKER_GUIDE.md)** - контейнеризация
- **[Система надежности](./RELIABILITY_GUIDE.md)** - мониторинг и устойчивость

### 4. Создание кастомных шаблонов

Используйте команду `/templates` в боте для создания собственных форматов протоколов.

## 🆘 Поддержка

### Получение помощи

1. **Команды бота**: `/help`, `/performance`, `/health`
2. **Логи**: `logs/bot.log`
3. **Документация**: папка `docs/`
4. **GitHub Issues**: для багов и предложений

### Полезные команды

```bash
# Перезапуск бота
pkill -f "python main.py"
python main.py

# Очистка временных файлов
rm -rf temp/* cache/*

# Проверка места на диске
df -h

# Проверка памяти
free -h
```

## 🎯 Заключение

Soroka готов к использованию! Основные шаги:

1. ✅ **Установка** - `./install.sh`
2. ✅ **Конфигурация** - настройте `.env`
3. ✅ **Запуск** - `python main.py`
4. ✅ **Тестирование** - отправьте файл в бота

Для продвинутых возможностей изучите полную документацию в папке `docs/`.

---

**Soroka** - умный помощник для создания протоколов встреч! 🚀
