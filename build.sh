#!/bin/bash

# Универсальный скрипт сборки Docker образа
# Поддерживает локальную оптимизированную сборку и multi-platform сборку

set -e

# Конфигурация
IMAGE_NAME="gihar/soroka"
DEFAULT_VERSION="latest"
LOCAL_TAG="soroka-bot:optimized"

# Функция для показа справки
show_help() {
    echo "🚀 Универсальный скрипт сборки Docker образа"
    echo "=============================================="
    echo ""
    echo "Использование:"
    echo "  ./build.sh [опции] [версия]"
    echo ""
    echo "Опции:"
    echo "  -l, --local      Локальная оптимизированная сборка (по умолчанию)"
    echo "  -m, --multi      Multi-platform сборка для Docker Hub"
    echo "  -c, --clean      Очистка старых образов перед сборкой"
    echo "  -h, --help       Показать эту справку"
    echo ""
    echo "Примеры:"
    echo "  ./build.sh                    # Локальная сборка"
    echo "  ./build.sh -l                 # Локальная сборка с очисткой"
    echo "  ./build.sh -m v1.0.0          # Multi-platform сборка версии 1.0.0"
    echo "  ./build.sh -m -c latest       # Multi-platform сборка с очисткой"
    echo ""
}

# Функция для локальной сборки
build_local() {
    local clean=$1
    local version=${2:-$DEFAULT_VERSION}
    
    echo "🔧 Начинаем локальную оптимизированную сборку..."
    echo "=============================================="
    echo "Образ: $LOCAL_TAG"
    echo "Версия: $version"
    echo ""
    
    if [ "$clean" = "true" ]; then
        echo "🧹 Очистка старых образов..."
        docker system prune -f
    fi
    
    echo "📦 Сборка оптимизированного образа..."
    docker build \
        --tag $LOCAL_TAG \
        --tag "soroka-bot:$version" \
        --build-arg BUILDKIT_INLINE_CACHE=1 \
        --progress=plain \
        .
    
    echo ""
    echo "📊 Размер образа:"
    docker images soroka-bot:optimized --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"
    
    # Сравнение с оригинальным образом (если есть)
    if docker images soroka-bot:latest --format "{{.Size}}" 2>/dev/null; then
        echo ""
        echo "📈 Сравнение размеров:"
        echo "Оригинальный образ:"
        docker images soroka-bot:latest --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"
        echo "Оптимизированный образ:"
        docker images soroka-bot:optimized --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"
    fi
    
    echo ""
    echo "✅ Локальная сборка завершена!"
    echo ""
    echo "🔍 Запуск контейнера:"
    echo "   docker run -d --name soroka-bot $LOCAL_TAG"
}

# Функция для multi-platform сборки
build_multi() {
    local clean=$1
    local version=${2:-$DEFAULT_VERSION}
    local platforms="linux/amd64,linux/arm64"
    
    echo "🚀 Сборка универсального multi-platform образа"
    echo "=============================================="
    echo "Образ: $IMAGE_NAME:$version"
    echo "Платформы: $platforms"
    echo ""
    
    if [ "$clean" = "true" ]; then
        echo "🧹 Очистка старых образов..."
        docker system prune -f
    fi
    
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
        --platform $platforms \
        --tag $IMAGE_NAME:$version \
        --tag $IMAGE_NAME:latest \
        --push \
        .
    
    echo ""
    echo "✅ Универсальный образ успешно собран и загружен в Docker Hub!"
    echo ""
    echo "📋 Информация об образе:"
    echo "   Имя: $IMAGE_NAME"
    echo "   Версия: $version"
    echo "   Платформы: $platforms"
    echo ""
    echo "🔍 Проверить образ можно командой:"
    echo "   docker buildx imagetools inspect $IMAGE_NAME:$version"
    echo ""
    echo "📖 Использование:"
    echo "   docker run -d --name soroka-bot $IMAGE_NAME:$version"
}

# Парсинг аргументов
MODE="local"
CLEAN="false"
VERSION=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -l|--local)
            MODE="local"
            shift
            ;;
        -m|--multi)
            MODE="multi"
            shift
            ;;
        -c|--clean)
            CLEAN="true"
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        -*)
            echo "❌ Неизвестная опция: $1"
            show_help
            exit 1
            ;;
        *)
            VERSION="$1"
            shift
            ;;
    esac
done

# Выполнение сборки
case $MODE in
    "local")
        build_local "$CLEAN" "$VERSION"
        ;;
    "multi")
        build_multi "$CLEAN" "$VERSION"
        ;;
    *)
        echo "❌ Неизвестный режим: $MODE"
        exit 1
        ;;
esac