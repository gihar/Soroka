#!/bin/bash

# Скрипт для исправления проблемы OOM Killer
# Автор: AI Assistant
# Дата: $(date)

set -e

echo "🛡️  Исправление проблемы OOM Killer для Soroka Bot"
echo "=================================================="

# Проверяем, что мы в правильной директории
if [ ! -f "main.py" ]; then
    echo "❌ Ошибка: Запустите скрипт из корневой директории проекта Soroka"
    exit 1
fi

# Проверяем права sudo
if [ "$EUID" -eq 0 ]; then
    echo "⚠️  Предупреждение: Не запускайте скрипт от root. Используйте sudo только для systemd команд."
fi

echo ""
echo "📋 План исправлений:"
echo "1. Остановка бота"
echo "2. Обновление systemd конфигурации"
echo "3. Очистка временных файлов"
echo "4. Перезапуск бота"
echo "5. Проверка статуса"
echo ""

read -p "Продолжить? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Отменено пользователем"
    exit 0
fi

echo ""
echo "🛑 Остановка бота..."
if systemctl is-active --quiet soroka; then
    sudo systemctl stop soroka
    echo "✅ Бот остановлен"
else
    echo "ℹ️  Бот уже остановлен"
fi

echo ""
echo "⚙️  Обновление systemd конфигурации..."

# Создаем резервную копию
if [ -f "/etc/systemd/system/soroka.service" ]; then
    sudo cp /etc/systemd/system/soroka.service /etc/systemd/system/soroka.service.backup.$(date +%Y%m%d_%H%M%S)
    echo "✅ Создана резервная копия конфигурации"
fi

# Обновляем конфигурацию
sudo tee /etc/systemd/system/soroka.service > /dev/null << 'EOF'
[Unit]
Description=Soroka telegram bot
After=network-online.target
Wants=network-online.target

[Service]
User=botuser
WorkingDirectory=/home/botuser/Soroka
EnvironmentFile=/home/botuser/Soroka/.env
ExecStart=/home/botuser/Soroka/venv/bin/python /home/botuser/Soroka/main.py
Restart=always
RestartSec=3
# Плавное завершение, чтобы успеть отослать ответы:
TimeoutStopSec=20
# Хелсчек через watchdog (опционально, если реализуете в коде):
# WatchdogSec=30s
# Type=notify

# Защита от OOM Killer - ограничения ресурсов:
MemoryMax=2G
MemoryHigh=1.5G
MemorySwapMax=1G
# Ограничение CPU (опционально):
# CPUQuota=200%

# Логи в journald:
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

echo "✅ Systemd конфигурация обновлена"

echo ""
echo "🔄 Перезагрузка systemd..."
sudo systemctl daemon-reload
echo "✅ Systemd перезагружен"

echo ""
echo "🧹 Очистка временных файлов..."
if [ -d "temp" ]; then
    rm -rf temp/*
    echo "✅ Временные файлы очищены"
else
    echo "ℹ️  Директория temp не найдена"
fi

echo ""
echo "🚀 Запуск бота..."
sudo systemctl start soroka
echo "✅ Бот запущен"

echo ""
echo "⏳ Ожидание запуска (10 секунд)..."
sleep 10

echo ""
echo "📊 Проверка статуса..."
if systemctl is-active --quiet soroka; then
    echo "✅ Бот успешно запущен"
    
    # Показываем статус
    echo ""
    echo "📈 Статус сервиса:"
    sudo systemctl status soroka --no-pager -l
    
    echo ""
    echo "💾 Использование памяти:"
    free -h
    
    echo ""
    echo "🔍 Процессы бота:"
    ps aux | grep -E "(main\.py|soroka)" | grep -v grep || echo "Процессы не найдены"
    
else
    echo "❌ Ошибка: Бот не запустился"
    echo ""
    echo "📋 Последние логи:"
    sudo journalctl -u soroka --no-pager -l -n 20
    exit 1
fi

echo ""
echo "🎯 Дополнительные команды для мониторинга:"
echo ""
echo "📊 Мониторинг памяти:"
echo "  python monitor_memory.py --once"
echo "  python monitor_memory.py --interval 30"
echo ""
echo "📋 Просмотр логов:"
echo "  sudo journalctl -u soroka -f"
echo ""
echo "🔍 Проверка OOM защиты:"
echo "  python monitor_memory.py --check-oom"
echo ""
echo "📈 Статус сервиса:"
echo "  sudo systemctl status soroka"
echo ""

echo "✅ Исправления применены успешно!"
echo ""
echo "🛡️  Ваш бот теперь защищен от OOM Killer:"
echo "   • Ограничение памяти: 2GB максимум"
echo "   • Автоматическая очистка при 85% использования"
echo "   • Мониторинг в реальном времени"
echo "   • Защищенная обработка больших файлов"
echo ""
echo "📚 Подробная документация: docs/OOM_PROTECTION_GUIDE.md"
