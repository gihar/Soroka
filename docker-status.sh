#!/bin/bash

echo "📊 Статус Telegram бота в Docker"
echo "================================"

# Проверяем наличие Docker Compose
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose не найден"
    exit 1
fi

# Показываем статус контейнера
echo "🔍 Статус контейнера:"
docker-compose ps

echo ""

# Проверяем, запущен ли контейнер
if docker-compose ps | grep -q "Up"; then
    echo "✅ Контейнер запущен и работает"
    
    # Показываем использование ресурсов
    echo ""
    echo "💾 Использование ресурсов:"
    docker stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}\t{{.BlockIO}}"
    
    # Показываем последние логи
    echo ""
    echo "📋 Последние логи (последние 5 строк):"
    docker-compose logs --tail=5
    
    # Проверяем файл логов приложения
    echo ""
    echo "📄 Последние записи в логе приложения:"
    if docker exec telegram-bot test -f logs/bot.log; then
        docker exec telegram-bot tail -3 logs/bot.log
    else
        echo "   Файл логов приложения не найден"
    fi
    
else
    echo "❌ Контейнер не запущен"
    echo ""
    echo "📋 Полезные команды:"
    echo "  Запуск: ./docker-run.sh"
    echo "  Логи: ./docker-logs.sh"
fi

echo ""
echo "📋 Полезные команды:"
echo "  Запуск: ./docker-run.sh"
echo "  Остановка: ./docker-stop.sh"
echo "  Логи: ./docker-logs.sh"
echo "  Перезапуск: docker-compose restart"
