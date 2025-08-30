#!/bin/bash

echo "🚀 Запуск Telegram бота в Docker контейнере"
echo "=========================================="

# Функция для вывода ошибки и завершения
error_exit() {
    echo "❌ Ошибка: $1"
    exit 1
}

# Функция для проверки команды
check_command() {
    if ! command -v $1 &> /dev/null; then
        error_exit "$1 не найден. Установите $1"
    fi
}

# Проверяем наличие необходимых команд
echo "🔍 Проверка зависимостей..."
check_command docker
check_command docker-compose

# Проверяем наличие .env файла
if [ ! -f ".env" ]; then
    echo "⚠️ Файл .env не найден. Копирую из примера..."
    if [ -f "env_example" ]; then
        cp env_example .env
        echo "📝 Файл .env создан из примера!"
        echo "⚠️  ВАЖНО: Отредактируйте файл .env с вашими настройками!"
        echo "   Особенно важно установить TELEGRAM_TOKEN!"
        echo ""
        echo "📋 Следующие шаги:"
        echo "   1. Отредактируйте файл .env"
        echo "   2. Запустите скрипт снова: ./docker-run.sh"
        exit 0
    else
        error_exit "Файл env_example не найден"
    fi
fi

# Проверяем, что TELEGRAM_TOKEN установлен
if ! grep -q "^TELEGRAM_TOKEN=.*[^[:space:]]" .env; then
    echo "⚠️  TELEGRAM_TOKEN не установлен в .env файле!"
    echo "   Отредактируйте файл .env и установите ваш токен"
    exit 1
fi

# Создаем необходимые директории
echo "📁 Создание директорий..."
mkdir -p data logs temp cache

# Создаем файл базы данных, если его нет
if [ ! -f "bot.db" ]; then
    echo "🗄️ Создание файла базы данных..."
    touch bot.db
fi

# Устанавливаем правильные права доступа
echo "🔐 Установка прав доступа..."
chmod 755 data logs temp cache
chmod 644 .env
chmod 666 bot.db

# Останавливаем существующие контейнеры
echo "🛑 Остановка существующих контейнеров..."
docker-compose down --remove-orphans 2>/dev/null || true

# Очищаем неиспользуемые образы (опционально)
read -p "🧹 Очистить неиспользуемые Docker образы? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "🧹 Очистка неиспользуемых образов..."
    docker image prune -f
fi

# Собираем и запускаем контейнер
echo "🐳 Сборка и запуск Docker контейнера..."
if ! docker-compose up --build -d; then
    error_exit "Не удалось собрать или запустить контейнер"
fi

# Ждем немного для запуска контейнера
echo "⏳ Ожидание запуска контейнера..."
sleep 5

# Проверяем статус контейнера
echo ""
echo "🔍 Проверка статуса контейнера..."
if docker-compose ps | grep -q "Up"; then
    echo "✅ Контейнер успешно запущен!"
else
    echo "❌ Контейнер не запущен. Проверьте логи:"
    echo "   docker-compose logs"
    exit 1
fi

# Показываем логи для диагностики
echo ""
echo "📋 Последние логи контейнера:"
docker-compose logs --tail=10

echo ""
echo "✅ Установка завершена успешно!"
echo ""
echo "📋 Полезные команды:"
echo "  Просмотр логов: docker-compose logs -f"
echo "  Остановка: docker-compose down"
echo "  Перезапуск: docker-compose restart"
echo "  Обновление: docker-compose up --build -d"
echo "  Статус: docker-compose ps"
echo ""
echo "🔍 Текущий статус:"
docker-compose ps
