#!/bin/bash

echo "📋 Просмотр логов Telegram бота"
echo "==============================="

# Проверяем наличие Docker Compose
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose не найден"
    exit 1
fi

# Проверяем, запущен ли контейнер
if ! docker-compose ps | grep -q "Up"; then
    echo "ℹ️  Контейнер не запущен"
    echo "   Запустите: ./docker-run.sh"
    exit 1
fi

# Показываем статус контейнера
echo "🔍 Статус контейнера:"
docker-compose ps

echo ""
echo "📋 Логи контейнера (последние 50 строк):"
echo "=========================================="

# Показываем логи
docker-compose logs --tail=50

echo ""
echo "📋 Полезные команды:"
echo "  Следить за логами в реальном времени: docker-compose logs -f"
echo "  Все логи: docker-compose logs"
echo "  Логи с определенной даты: docker-compose logs --since='2024-01-01'"
echo "  Остановить слежение: Ctrl+C"
