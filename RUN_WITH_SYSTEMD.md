
Long polling + systemd — минимальная сложность, идеально для 1-инстанса на VPS.
systemd unit: автозапуск и перезапуск

/etc/systemd/system/soroka.service

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

Для запуска:
sudo systemctl daemon-reload
sudo systemctl enable --now soroka
journalctl -u soroka -f