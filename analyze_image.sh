#!/bin/bash

# Скрипт для анализа размера Docker образа
# Помогает найти возможности для дальнейшей оптимизации

set -e

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Функция для показа справки
show_help() {
    echo -e "${BLUE}🔍 Скрипт анализа размера Docker образа${NC}"
    echo "=============================================="
    echo ""
    echo "Использование:"
    echo "  ./analyze_image.sh [имя_образа]"
    echo ""
    echo "Примеры:"
    echo "  ./analyze_image.sh soroka-bot:latest"
    echo "  ./analyze_image.sh soroka-bot:optimized"
    echo ""
}

# Функция для анализа размера образа
analyze_image() {
    local image_name=$1
    
    if [ -z "$image_name" ]; then
        echo -e "${RED}❌ Не указано имя образа${NC}"
        show_help
        exit 1
    fi
    
    # Проверяем существование образа
    if ! docker images "$image_name" --format "{{.Repository}}:{{.Tag}}" | grep -q "$image_name"; then
        echo -e "${RED}❌ Образ $image_name не найден${NC}"
        exit 1
    fi
    
    echo -e "${BLUE}🔍 Анализ образа: $image_name${NC}"
    echo "=============================================="
    echo ""
    
    # Основная информация об образе
    echo -e "${GREEN}📊 Основная информация:${NC}"
    docker images "$image_name" --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}"
    echo ""
    
    # Анализ слоев
    echo -e "${GREEN}🔍 Анализ слоев:${NC}"
    echo "Слои отсортированы по размеру (от большего к меньшему):"
    echo ""
    
    # Получаем информацию о слоях и сортируем по размеру
    docker history "$image_name" --format "{{.Size}}\t{{.CreatedBy}}" | \
    while IFS=$'\t' read -r size command; do
        if [[ "$size" != "<missing>" ]]; then
            echo -e "${YELLOW}$size${NC}\t$command"
        fi
    done | sort -hr
    echo ""
    
    # Анализ содержимого образа
    echo -e "${GREEN}📁 Анализ содержимого:${NC}"
    echo "Создаем временный контейнер для анализа..."
    
    # Создаем временный контейнер
    local temp_container=$(docker create "$image_name")
    
    if [ -n "$temp_container" ]; then
        echo "Контейнер создан: $temp_container"
        
        # Анализируем размеры директорий
        echo ""
        echo -e "${YELLOW}📊 Размеры директорий:${NC}"
        docker exec "$temp_container" sh -c "du -sh /* 2>/dev/null | sort -hr" 2>/dev/null || \
        docker exec "$temp_container" sh -c "du -sh /app/* 2>/dev/null | sort -hr" 2>/dev/null || \
        echo "Не удалось получить информацию о размерах директорий"
        
        # Анализируем Python пакеты
        echo ""
        echo -e "${YELLOW}🐍 Python пакеты:${NC}"
        docker exec "$temp_container" sh -c "pip list --format=freeze 2>/dev/null | wc -l" 2>/dev/null || \
        echo "Не удалось получить информацию о Python пакетах"
        
        # Анализируем системные пакеты
        echo ""
        echo -e "${YELLOW}📦 Системные пакеты:${NC}"
        docker exec "$temp_container" sh -c "dpkg -l | wc -l 2>/dev/null" 2>/dev/null || \
        echo "Не удалось получить информацию о системных пакетах"
        
        # Удаляем временный контейнер
        docker rm "$temp_container" >/dev/null 2>&1
        echo ""
        echo "Временный контейнер удален"
    else
        echo -e "${RED}Не удалось создать временный контейнер${NC}"
    fi
    
    # Рекомендации по оптимизации
    echo ""
    echo -e "${GREEN}💡 Рекомендации по оптимизации:${NC}"
    echo "=============================================="
    
    # Анализируем размер образа
    local image_size=$(docker images "$image_name" --format "{{.Size}}" | sed 's/[^0-9.]//g')
    
    if [[ "$image_size" =~ ^[0-9.]+$ ]]; then
        if (( $(echo "$image_size > 1000" | bc -l) )); then
            echo -e "${RED}⚠️  Образ очень большой (>1GB). Рекомендуется:${NC}"
            echo "   - Использовать multi-stage сборку"
            echo "   - Убрать ненужные зависимости"
            echo "   - Использовать .dockerignore"
            echo "   - Сжать слои (--squash)"
        elif (( $(echo "$image_size > 500" | bc -l) )); then
            echo -e "${YELLOW}⚠️  Образ большой (>500MB). Рекомендуется:${NC}"
            echo "   - Проверить .dockerignore"
            echo "   - Убрать dev-зависимости"
            echo "   - Использовать легкие базовые образы"
        else
            echo -e "${GREEN}✅ Образ имеет приемлемый размер${NC}"
        fi
    fi
    
    echo ""
    echo -e "${BLUE}🔧 Команды для оптимизации:${NC}"
    echo "   ./build.sh -s -x          # Сборка со сжатием и исключением файлов"
    echo "   ./build.sh -c             # Сборка с очисткой кэша"
    echo "   docker system prune -a    # Полная очистка Docker"
    echo ""
    
    echo -e "${GREEN}✅ Анализ завершен${NC}"
}

# Основная логика
if [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    show_help
    exit 0
fi

analyze_image "$1"
