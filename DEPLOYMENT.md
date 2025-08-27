# Руководство по развертыванию Soroka Bot

## Быстрое развертывание

### 1. Системные требования

- Python 3.11+
- FFmpeg для обработки аудио
- 8GB+ RAM рекомендуется
- SSD диск для лучшей производительности

### 2. Установка зависимостей

```bash
# Клонирование репозитория
git clone https://github.com/gihar/Soroka.git
cd Soroka

# Установка зависимостей
chmod +x install.sh
./install.sh
```

### 3. Настройка окружения

```bash
# Копирование файла окружения
cp .env.example .env

# Редактирование настроек
nano .env
```

### 4. Настройка переменных окружения

Обязательные переменные:
- `TELEGRAM_BOT_TOKEN` - токен Telegram бота
- `OPENAI_API_KEY` - ключ OpenAI API
- `DATABASE_URL` - путь к базе данных

Опциональные:
- `ANTHROPIC_API_KEY` - для Claude
- `GEMINI_API_KEY` - для Google Gemini
- `OPENROUTER_API_KEY` - для OpenRouter

### 5. Запуск

```bash
# Активация виртуального окружения
source venv/bin/activate

# Инициализация базы данных
python database.py

# Запуск бота
python main.py
```

## Docker развертывание

```bash
# Создание Docker образа
docker build -t soroka-bot .

# Запуск контейнера
docker run -d --name soroka-bot \
  --env-file .env \
  -v $(pwd)/bot.db:/app/bot.db \
  soroka-bot
```

## Системные сервисы

### systemd сервис

Создайте файл `/etc/systemd/system/soroka-bot.service`:

```ini
[Unit]
Description=Soroka Telegram Bot
After=network.target

[Service]
Type=simple
User=soroka
WorkingDirectory=/opt/soroka
ExecStart=/opt/soroka/venv/bin/python main.py
Restart=always
RestartSec=5
Environment=PYTHONPATH=/opt/soroka

[Install]
WantedBy=multi-user.target
```

Активация:
```bash
sudo systemctl enable soroka-bot
sudo systemctl start soroka-bot
```

## Мониторинг

### Логи
```bash
# Просмотр логов
tail -f logs/bot.log

# Системные логи
sudo journalctl -u soroka-bot -f
```

### Метрики производительности
Бот включает встроенную систему метрик. Доступ через API:
```bash
curl http://localhost:8000/metrics
curl http://localhost:8000/health
```

## Резервное копирование

```bash
# Бэкап базы данных
cp bot.db backups/bot_$(date +%Y%m%d_%H%M%S).db

# Бэкап конфигурации
tar -czf backup_$(date +%Y%m%d).tar.gz .env config.py
```

## Безопасность

- Используйте HTTPS для webhook URL
- Регулярно обновляйте зависимости
- Мониторьте логи на предмет подозрительной активности
- Настройте rate limiting
- Используйте секретные ключи только через переменные окружения

## Устранение неполадок

### Проблемы с аудио
```bash
# Проверка FFmpeg
ffmpeg -version

# Права доступа к temp директории
chmod 755 temp/
```

### Проблемы с базой данных
```bash
# Пересоздание таблиц
python -c "from database import init_db; init_db()"
```

### Проблемы с памятью
- Увеличьте RAM
- Настройте swap
- Оптимизируйте размер batch для обработки

## Производительность

### Рекомендуемые настройки
- `MAX_WORKERS=4` для обработки
- `CACHE_SIZE=1000` для кеша
- `BATCH_SIZE=10` для batch обработки

### Оптимизация
- Используйте SSD диски
- Настройте кеширование Redis (опционально)
- Мониторьте использование памяти
