#!/bin/bash

echo "🚀 Развертывание Soroka Bot на NAS"
echo "=================================="

# Проверяем наличие .env файла
if [ ! -f ".env" ]; then
    echo "❌ Файл .env не найден!"
    echo "📝 Создайте файл .env с вашими настройками:"
    echo ""
    echo "TELEGRAM_TOKEN=your_telegram_token"
    echo "OPENAI_API_KEY=your_openai_key"
    echo "GROQ_API_KEY=your_groq_key"
    echo ""
    echo "Пример:"
    echo "cp env_example .env"
    echo "nano .env"
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
docker-compose -f docker-compose.nas.yml down --remove-orphans 2>/dev/null || true

# Запускаем контейнер
echo "🐳 Запуск контейнера..."
docker-compose -f docker-compose.nas.yml up -d

# Ждем немного для запуска
echo "⏳ Ожидание запуска..."
sleep 10

# Проверяем статус
echo ""
echo "🔍 Проверка статуса..."
if docker-compose -f docker-compose.nas.yml ps | grep -q "Up"; then
    echo "✅ Контейнер успешно запущен!"
else
    echo "❌ Контейнер не запущен. Проверьте логи:"
    echo "   docker-compose -f docker-compose.nas.yml logs"
    exit 1
fi

# Показываем логи
echo ""
echo "📋 Последние логи:"
docker-compose -f docker-compose.nas.yml logs --tail=20

echo ""
echo "✅ Развертывание завершено!"
echo ""
echo "📋 Полезные команды:"
echo "  Просмотр логов: docker-compose -f docker-compose.nas.yml logs -f"
echo "  Остановка: docker-compose -f docker-compose.nas.yml down"
echo "  Перезапуск: docker-compose -f docker-compose.nas.yml restart"
echo "  Обновление: docker-compose -f docker-compose.nas.yml pull && docker-compose -f docker-compose.nas.yml up -d"
echo ""
echo "🔍 Статус:"
docker-compose -f docker-compose.nas.yml ps
