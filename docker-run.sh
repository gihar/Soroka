#!/bin/bash

echo "🚀 Запуск Telegram бота в Docker контейнере"
echo "=========================================="

# Проверяем наличие Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker не найден. Установите Docker:"
    echo "   https://docs.docker.com/get-docker/"
    exit 1
fi

# Проверяем наличие Docker Compose
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose не найден. Установите Docker Compose:"
    echo "   https://docs.docker.com/compose/install/"
    exit 1
fi

# Проверяем наличие .env файла
if [ ! -f ".env" ]; then
    echo "⚠️ Файл .env не найден. Копирую из примера..."
    if [ -f "env_example" ]; then
        cp env_example .env
        echo "📝 Не забудьте отредактировать файл .env с вашими настройками!"
        echo "   Особенно важно установить TELEGRAM_TOKEN!"
        exit 1
    else
        echo "❌ Файл env_example не найден."
        exit 1
    fi
fi

# Создаем необходимые директории
echo "📁 Создание директорий..."
mkdir -p data logs temp cache

# Собираем и запускаем контейнер
echo "🐳 Сборка и запуск Docker контейнера..."
docker-compose up --build -d

echo ""
echo "✅ Контейнер запущен!"
echo ""
echo "📋 Полезные команды:"
echo "  Просмотр логов: docker-compose logs -f"
echo "  Остановка: docker-compose down"
echo "  Перезапуск: docker-compose restart"
echo "  Обновление: docker-compose up --build -d"
echo ""
echo "🔍 Проверка статуса: docker-compose ps"
