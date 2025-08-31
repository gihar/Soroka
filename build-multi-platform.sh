#!/bin/bash

# Скрипт для сборки универсального multi-platform образа
# Поддерживает: linux/amd64, linux/arm64, linux/arm/v7

set -e

# Конфигурация
IMAGE_NAME="gihar/soroka"  # Замените на ваш username
VERSION=${1:-latest}
PLATFORMS="linux/amd64,linux/arm64"

echo "🚀 Сборка универсального multi-platform образа"
echo "=============================================="
echo "Образ: $IMAGE_NAME:$VERSION"
echo "Платформы: $PLATFORMS"
echo ""

# Проверяем наличие Docker Buildx
if ! docker buildx version &> /dev/null; then
    echo "❌ Docker Buildx не найден. Установите Docker Desktop или обновите Docker."
    exit 1
fi

# Создаем новый builder для multi-platform сборки
echo "🔧 Настройка multi-platform builder..."
docker buildx create --name multiplatform-builder --use 2>/dev/null || \
docker buildx use multiplatform-builder

# Проверяем, что builder поддерживает multi-platform
if ! docker buildx inspect --bootstrap | grep -q "linux/amd64\|linux/arm64"; then
    echo "❌ Ваш Docker не поддерживает multi-platform сборку."
    echo "   Убедитесь, что используете Docker Desktop или Docker с поддержкой Buildx."
    exit 1
fi

# Собираем multi-platform образ
echo "🐳 Сборка образа для всех платформ..."
docker buildx build \
    --platform $PLATFORMS \
    --tag $IMAGE_NAME:$VERSION \
    --tag $IMAGE_NAME:latest \
    --push \
    .

echo ""
echo "✅ Универсальный образ успешно собран и загружен в Docker Hub!"
echo ""
echo "📋 Информация об образе:"
echo "   Имя: $IMAGE_NAME"
echo "   Версия: $VERSION"
echo "   Платформы: $PLATFORMS"
echo ""
echo "🔍 Проверить образ можно командой:"
echo "   docker buildx imagetools inspect $IMAGE_NAME:$VERSION"
echo ""
echo "📖 Использование:"
echo "   docker run -d --name soroka-bot $IMAGE_NAME:$VERSION"
