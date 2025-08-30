#!/bin/bash

echo "🛑 Остановка Telegram бота в Docker контейнере"
echo "============================================="

# Проверяем наличие Docker Compose
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose не найден"
    exit 1
fi

# Проверяем, запущен ли контейнер
if ! docker-compose ps | grep -q "Up"; then
    echo "ℹ️  Контейнер уже остановлен"
    exit 0
fi

# Останавливаем контейнер
echo "🛑 Остановка контейнера..."
docker-compose down

# Очищаем неиспользуемые ресурсы (опционально)
read -p "🧹 Удалить неиспользуемые образы и тома? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "🧹 Очистка неиспользуемых ресурсов..."
    docker system prune -f
fi

echo ""
echo "✅ Контейнер остановлен!"
echo ""
echo "📋 Полезные команды:"
echo "  Запуск: ./docker-run.sh"
echo "  Статус: docker-compose ps"
echo "  Логи: docker-compose logs"
