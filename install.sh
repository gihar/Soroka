#!/bin/bash

echo "🚀 Установка Telegram бота для создания протоколов встреч"
echo "============================================================"

# Проверяем Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 не найден. Установите Python 3.10 или новее."
    exit 1
fi

# Проверяем версию Python
python_version=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if [[ "$python_version" < "3.10" ]]; then
    echo "❌ Требуется Python 3.10 или новее. Текущая версия: $python_version"
    exit 1
fi

echo "✅ Python $python_version найден"

# Проверяем и устанавливаем ffmpeg
echo "🎬 Проверка ffmpeg..."
if ! command -v ffmpeg &> /dev/null; then
    echo "⚠️ ffmpeg не найден. Устанавливаем..."
    
    # Определяем операционную систему
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        if command -v brew &> /dev/null; then
            echo "🍺 Установка ffmpeg через Homebrew..."
            brew install ffmpeg
        else
            echo "❌ Homebrew не найден. Установите Homebrew или ffmpeg вручную:"
            echo "   Homebrew: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
            echo "   Затем: brew install ffmpeg"
            exit 1
        fi
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        # Linux
        if command -v apt-get &> /dev/null; then
            echo "🐧 Установка ffmpeg через apt..."
            sudo apt-get update
            sudo apt-get install -y ffmpeg
        elif command -v yum &> /dev/null; then
            echo "🐧 Установка ffmpeg через yum..."
            sudo yum install -y ffmpeg
        elif command -v pacman &> /dev/null; then
            echo "🐧 Установка ffmpeg через pacman..."
            sudo pacman -S ffmpeg
        else
            echo "❌ Неизвестный пакетный менеджер. Установите ffmpeg вручную."
            exit 1
        fi
    else
        echo "❌ Неподдерживаемая операционная система: $OSTYPE"
        echo "Установите ffmpeg вручную и запустите скрипт снова."
        exit 1
    fi
    
    # Проверяем успешность установки
    if command -v ffmpeg &> /dev/null; then
        echo "✅ ffmpeg успешно установлен"
    else
        echo "❌ Не удалось установить ffmpeg. Установите его вручную."
        exit 1
    fi
else
    echo "✅ ffmpeg уже установлен"
fi

# Создаем виртуальное окружение
echo "📦 Создание виртуального окружения..."
python3 -m venv venv

# Активируем виртуальное окружение
echo "🔧 Активация виртуального окружения..."
source venv/bin/activate

# Обновляем pip
echo "⬆️ Обновление pip..."
pip install --upgrade pip

# Устанавливаем зависимости
echo "📚 Установка зависимостей..."
pip install -r requirements.txt

# Создаем необходимые директории
echo "📁 Создание директорий..."
mkdir -p logs temp

# Проверяем наличие файла .env
if [ ! -f ".env" ]; then
    echo "⚠️ Файл .env не найден. Копирую из примера..."
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "📝 Не забудьте отредактировать файл .env с вашими настройками!"
    else
        echo "❌ Файл .env.example не найден."
    fi
fi

echo ""
echo "✅ Установка завершена!"
echo ""
echo "📋 Следующие шаги:"
echo "1. Отредактируйте файл .env с вашими API ключами"
echo "2. Запустите бота: python main.py"
echo ""
echo "🔧 Для активации виртуального окружения в будущем:"
echo "   source venv/bin/activate"
echo ""
echo "📖 Подробная документация в файле README.md"
