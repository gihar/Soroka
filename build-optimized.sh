#!/bin/bash

# Скрипт для оптимизированной сборки Docker образа
set -e

echo "🔧 Начинаем оптимизированную сборку Docker образа..."

# Очистка старых образов
echo "🧹 Очистка старых образов..."
docker system prune -f

# Сборка с оптимизированным Dockerfile
echo "📦 Сборка оптимизированного образа..."
docker build \
    --file Dockerfile.optimized \
    --tag soroka-bot:optimized \
    --build-arg BUILDKIT_INLINE_CACHE=1 \
    --progress=plain \
    .

# Показываем размер образа
echo "📊 Размер образа:"
docker images soroka-bot:optimized --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"

# Сравнение с оригинальным образом (если есть)
if docker images soroka-bot:latest --format "{{.Size}}" 2>/dev/null; then
    echo "📈 Сравнение размеров:"
    echo "Оригинальный образ:"
    docker images soroka-bot:latest --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"
    echo "Оптимизированный образ:"
    docker images soroka-bot:optimized --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"
fi

echo "✅ Оптимизированная сборка завершена!"
