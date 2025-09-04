#!/bin/bash

# Универсальный скрипт сборки Docker образа
# Поддерживает локальную оптимизированную сборку и multi-platform сборку
# Оптимизирован для создания образов минимального размера

set -e

# Конфигурация
IMAGE_NAME="gihar/soroka"
DEFAULT_VERSION="latest"
LOCAL_TAG="soroka-bot:optimized"

# Функция для показа справки
show_help() {
    echo "🚀 Универсальный скрипт сборки Docker образа (оптимизированный)"
    echo "================================================================"
    echo ""
    echo "Использование:"
    echo "  ./build.sh [опции] [версия]"
    echo ""
    echo "Опции:"
    echo "  -l, --local      Локальная оптимизированная сборка (по умолчанию)"
    echo "  -m, --multi      Multi-platform сборка для Docker Hub"
    echo "  -c, --clean      Очистка старых образов перед сборкой"
    echo "  -s, --squash     Сжатие слоев для уменьшения размера (только для локальной сборки)"
    echo "  -x, --exclude    Исключить ненужные файлы из контекста сборки"
    echo "  --lite           Сборка лёгкого образа (без Whisper/Torch/pyannote)"
    echo "  -h, --help       Показать эту справку"
    echo ""
    echo "Примеры:"
    echo "  ./build.sh                    # Локальная сборка"
    echo "  ./build.sh -l -s              # Локальная сборка со сжатием"
    echo "  ./build.sh -m v1.0.0          # Multi-platform сборка версии 1.0.0"
    echo "  ./build.sh -m -c latest       # Multi-platform сборка с очисткой"
    echo "  ./build.sh -x                 # Сборка с исключением ненужных файлов"
    echo "  ./build.sh --lite             # Локальная лёгкая сборка без тяжёлых ML"
    echo ""
}

# Функция для создания .dockerignore для оптимизации
create_optimized_dockerignore() {
    echo "🔧 Создание оптимизированного .dockerignore..."
    cat > .dockerignore << 'EOF'
# Git и версионирование
.git
.gitignore
.gitattributes

# Документация
docs/
*.md
README*

# Временные файлы и кэш
temp/
cache/
logs/
*.log
__pycache__/
*.pyc
*.pyo
*.pyd
.Python
env/
venv/
.venv/
ENV/
env.bak/
venv.bak/

# IDE и редакторы
.vscode/
.idea/
*.swp
*.swo
*~

# Системные файлы
.DS_Store
Thumbs.db

# Docker файлы
Dockerfile*
docker-compose*.yml
.dockerignore

# Скрипты сборки и развертывания
build.sh
install.sh
*.sh

# Тесты
tests/
test_*.py
*_test.py

# Конфигурация разработки
.env
.env.local
.env.development

# База данных
*.db
*.sqlite
*.sqlite3

# Локальные настройки
config.local.py
config.dev.py
EOF
    echo "✅ .dockerignore создан"
}

# Функция для очистки Docker системы
clean_docker_system() {
    echo "🧹 Глубокая очистка Docker системы..."
    
    # Удаление неиспользуемых образов
    echo "  Удаление неиспользуемых образов..."
    docker image prune -a -f 2>/dev/null || true
    
    # Удаление неиспользуемых контейнеров
    echo "  Удаление неиспользуемых контейнеров..."
    docker container prune -f 2>/dev/null || true
    
    # Удаление неиспользуемых сетей
    echo "  Удаление неиспользуемых сетей..."
    docker network prune -f 2>/dev/null || true
    
    # Удаление неиспользуемых томов
    echo "  Удаление неиспользуемых томов..."
    docker volume prune -f 2>/dev/null || true
    
    # Удаление неиспользуемых build cache
    echo "  Удаление неиспользуемого build cache..."
    docker builder prune -a -f 2>/dev/null || true
    
    # Полная очистка системы
    echo "  Полная очистка системы..."
    docker system prune -a -f 2>/dev/null || true
    
    echo "✅ Очистка завершена"
}

# Функция для локальной сборки
build_local() {
    local clean=$1
    local squash=$2
    local exclude=$3
    local version=${4:-$DEFAULT_VERSION}
    local lite=${5:-false}
    
    echo "🔧 Начинаем локальную оптимизированную сборку..."
    echo "=============================================="
    echo "Образ: $LOCAL_TAG"
    echo "Версия: $version"
    echo "Сжатие слоев: $squash"
    echo "Исключение файлов: $exclude"
    echo ""
    
    if [ "$clean" = "true" ]; then
        clean_docker_system
    fi
    
    if [ "$exclude" = "true" ]; then
        create_optimized_dockerignore
    fi
    
    # Оптимизированные флаги сборки
    local build_flags="--tag $LOCAL_TAG --tag soroka-bot:$version"
    if [ "$lite" = "true" ]; then
        build_flags="$build_flags --build-arg FLAVOR=lite"
        echo "🍃 Включён лёгкий режим: FLAVOR=lite"
    else
        build_flags="$build_flags --build-arg FLAVOR=full"
    fi
    
    # Добавляем сжатие слоев если запрошено
    if [ "$squash" = "true" ]; then
        build_flags="$build_flags --squash"
        echo "📦 Включено сжатие слоев для уменьшения размера..."
    fi
    
    # Добавляем оптимизации для уменьшения размера
    build_flags="$build_flags --build-arg BUILDKIT_INLINE_CACHE=1"
    build_flags="$build_flags --build-arg DOCKER_BUILDKIT=1"
    build_flags="$build_flags --progress=plain"
    
    # Добавляем метки для лучшего управления
    build_flags="$build_flags --label org.opencontainers.image.version=$version"
    build_flags="$build_flags --label org.opencontainers.image.created=$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
    build_flags="$build_flags --label org.opencontainers.image.description=Soroka-Bot-optimized-image"
    
    echo "📦 Сборка оптимизированного образа..."
    
    # Используем buildx для локальной сборки тоже, поскольку Docker перенаправляет build на buildx
    build_flags="$build_flags --load"
    
    docker buildx build $build_flags .
    
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
        
        # Показываем процент уменьшения
        local original_size=$(docker images soroka-bot:latest --format "{{.Size}}" | sed 's/[^0-9.]//g')
        local optimized_size=$(docker images soroka-bot:optimized --format "{{.Size}}" | sed 's/[^0-9.]//g')
        if [[ "$original_size" =~ ^[0-9.]+$ ]] && [[ "$optimized_size" =~ ^[0-9.]+$ ]]; then
            local reduction=$(echo "scale=1; (($original_size - $optimized_size) / $original_size) * 100" | bc -l 2>/dev/null || echo "0")
            echo ""
            echo "🎯 Уменьшение размера: ${reduction}%"
        fi
    fi
    
    # Анализ слоев образа
    echo ""
    echo "🔍 Анализ слоев образа:"
    docker history soroka-bot:optimized --format "table {{.CreatedBy}}\t{{.Size}}\t{{.CreatedAt}}" | head -10
    
    echo ""
    echo "✅ Локальная сборка завершена!"
    echo ""
    echo "🔍 Запуск контейнера:"
    echo "   docker run -d --name soroka-bot $LOCAL_TAG"
    
    # Удаляем временный .dockerignore если он был создан
    if [ "$exclude" = "true" ]; then
        rm -f .dockerignore
        echo "🧹 Временный .dockerignore удален"
    fi
}

# Функция для multi-platform сборки
build_multi() {
    local clean=$1
    local version=${2:-$DEFAULT_VERSION}
    local lite=${3:-false}
    local platforms="linux/amd64,linux/arm64"
    
    echo "🚀 Сборка универсального multi-platform образа"
    echo "=============================================="
    echo "Образ: $IMAGE_NAME:$version"
    echo "Платформы: $platforms"
    echo ""
    
    if [ "$clean" = "true" ]; then
        clean_docker_system
    fi
    
    # Проверяем наличие Docker daemon
    if ! docker info &> /dev/null; then
        echo "❌ Docker daemon не запущен. Запустите Docker Desktop или Docker daemon."
        echo "   Попробуйте: open -a 'Docker Desktop' (на macOS)"
        exit 1
    fi
    
    # Проверяем наличие Docker Buildx
    if ! docker buildx version &> /dev/null; then
        echo "❌ Docker Buildx не найден. Установите Docker Desktop или обновите Docker."
        exit 1
    fi
    
    # Создаем новый builder для multi-platform сборки
    echo "🔧 Настройка multi-platform builder..."
    
    # Проверяем, есть ли уже подходящий builder
    if docker buildx ls | grep -q "multiplatform-builder.*running"; then
        echo "✅ Используем существующий multiplatform-builder"
        docker buildx use multiplatform-builder
    elif docker buildx ls | grep -E "default.*running.*linux/amd64.*linux/arm64|desktop-linux.*running.*linux/amd64.*linux/arm64" &> /dev/null; then
        echo "✅ Используем системный builder с поддержкой multi-platform"
        # Используем системный builder, который уже поддерживает нужные платформы
    else
        # Создаем новый builder только если нужно
        echo "🔧 Создание нового multi-platform builder..."
        if docker buildx create --name multiplatform-builder --use 2>/dev/null; then
            echo "✅ Новый multiplatform-builder создан"
        else
            echo "⚠️  Используем существующий multiplatform-builder"
            docker buildx use multiplatform-builder
        fi
    fi
    
    # Проверяем, что активный builder поддерживает multi-platform
    echo "🔍 Проверка поддержки платформ..."
    if ! docker buildx inspect --bootstrap 2>/dev/null | grep -q "linux/amd64\|linux/arm64"; then
        echo "❌ Активный builder не поддерживает multi-platform сборку."
        echo "   Информация о builder:"
        docker buildx ls | head -10
        echo ""
        echo "   Попробуйте:"
        echo "   1. Перезапустить Docker Desktop"
        echo "   2. Обновить Docker Desktop до последней версии"
        echo "   3. Использовать локальную сборку: ./build.sh -l"
        echo ""
        echo "🔄 Автоматически переключаемся на локальную сборку..."
        echo ""
        build_local "$clean" "false" "false" "$version" "$lite"
        return
    fi
    
    echo "✅ Multi-platform сборка готова"
    
    # Оптимизированные флаги для multi-platform сборки
    local build_flags="--platform $platforms"
    build_flags="$build_flags --tag $IMAGE_NAME:$version"
    build_flags="$build_flags --tag $IMAGE_NAME:latest"
    if [ "$lite" = "true" ]; then
        build_flags="$build_flags --build-arg FLAVOR=lite"
        echo "🍃 Включён лёгкий режим: FLAVOR=lite"
    else
        build_flags="$build_flags --build-arg FLAVOR=full"
    fi
    build_flags="$build_flags --build-arg BUILDKIT_INLINE_CACHE=1"
    build_flags="$build_flags --build-arg DOCKER_BUILDKIT=1"
    build_flags="$build_flags --cache-from type=registry,ref=$IMAGE_NAME:buildcache"
    build_flags="$build_flags --cache-to type=registry,ref=$IMAGE_NAME:buildcache,mode=max"
    build_flags="$build_flags --push"
    
    # Собираем multi-platform образ
    echo "🐳 Сборка образа для всех платформ..."
    docker buildx build $build_flags .
    
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
SQUASH="false"
EXCLUDE="false"
VERSION=""
LITE="false"

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
        -s|--squash)
            SQUASH="true"
            shift
            ;;
        -x|--exclude)
            EXCLUDE="true"
            shift
            ;;
        --lite)
            LITE="true"
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
        build_local "$CLEAN" "$SQUASH" "$EXCLUDE" "$VERSION" "$LITE"
        ;;
    "multi")
        build_multi "$CLEAN" "$VERSION" "$LITE"
        ;;
    *)
        echo "❌ Неизвестный режим: $MODE"
        exit 1
        ;;
esac
