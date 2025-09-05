# 🛡️ Руководство по защите от OOM Killer

## 🚨 Проблема

Ваш Telegram бот Soroka был убит системой из-за нехватки памяти (OOM Killer). Это происходит когда:

1. **Загружаются большие ML модели** (Whisper, WhisperX, pyannote.audio)
2. **Обрабатываются большие аудио/видео файлы**
3. **Накопление объектов в памяти** (кэш, временные файлы)
4. **Отсутствие контроля использования памяти**

## ✅ Решение

Реализована комплексная система защиты от OOM Killer:

### 1. 🛡️ OOM Protection System

**Файл:** `src/performance/oom_protection.py`

- **Мониторинг памяти** в реальном времени
- **Автоматическая очистка** при критических ситуациях
- **Проверка файлов** перед обработкой
- **Callbacks** для уведомлений и очистки

### 2. 🔧 Обновленные сервисы

**Транскрипция:** `src/services/transcription_service.py`
- Проверка размера файла и доступной памяти
- Защищенная загрузка моделей Whisper
- Автоматическая очистка моделей при нехватке памяти

**Диаризация:** `diarization.py`
- Защищенная загрузка моделей WhisperX и pyannote
- Очистка CUDA кэша при агрессивной очистке
- Мониторинг использования памяти

### 3. ⚙️ Обновленная конфигурация systemd

**Файл:** `RUN_WITH_SYSTEMD.md`

```ini
[Service]
# Защита от OOM Killer - ограничения ресурсов:
MemoryMax=2G          # Максимум 2GB памяти
MemoryHigh=1.5G       # Предупреждение при 1.5GB
MemorySwapMax=1G      # Максимум 1GB swap
```

### 4. 📊 Мониторинг памяти

**Скрипт:** `monitor_memory.py`

```bash
# Непрерывный мониторинг
python monitor_memory.py

# Одноразовая проверка
python monitor_memory.py --once

# Проверка OOM защиты
python monitor_memory.py --check-oom
```

## 🚀 Как применить исправления

### 1. Обновите systemd конфигурацию

```bash
# Остановите бота
sudo systemctl stop soroka

# Обновите конфигурацию
sudo nano /etc/systemd/system/soroka.service

# Добавьте ограничения памяти:
MemoryMax=2G
MemoryHigh=1.5G
MemorySwapMax=1G

# Перезагрузите systemd
sudo systemctl daemon-reload

# Запустите бота
sudo systemctl start soroka
```

### 2. Проверьте статус

```bash
# Статус сервиса
sudo systemctl status soroka

# Логи
journalctl -u soroka -f

# Мониторинг памяти
python monitor_memory.py --once
```

### 3. Настройте мониторинг

```bash
# Сделайте скрипт исполняемым
chmod +x monitor_memory.py

# Запустите мониторинг в фоне
nohup python monitor_memory.py --interval 30 > memory_monitor.log 2>&1 &
```

## 📈 Лимиты и пороги

### Память
- **Максимальный размер файла:** 100MB
- **Предупреждение:** 85% использования памяти
- **Критический уровень:** 95% использования памяти
- **Минимальная доступная память:** 200MB

### Systemd ограничения
- **MemoryMax:** 2GB (жесткий лимит)
- **MemoryHigh:** 1.5GB (мягкий лимит)
- **MemorySwapMax:** 1GB (лимит swap)

## 🔍 Диагностика

### Проверка использования памяти

```bash
# Общая информация о памяти
free -h

# Процессы с наибольшим использованием памяти
ps aux --sort=-%mem | head -10

# Детальная информация о процессе бота
ps -p $(pgrep -f "main.py") -o pid,ppid,cmd,%mem,%cpu,rss,vsz
```

### Анализ логов

```bash
# Поиск OOM событий
journalctl -u soroka | grep -i "oom\|memory\|killed"

# Последние ошибки
journalctl -u soroka --since "1 hour ago" | grep -i error
```

### Мониторинг в реальном времени

```bash
# Запуск мониторинга
python monitor_memory.py --interval 5

# Проверка OOM защиты
python monitor_memory.py --check-oom
```

## ⚠️ Предупреждения

1. **Не отключайте OOM Protection** без крайней необходимости
2. **Мониторьте логи** на предмет предупреждений о памяти
3. **Регулярно очищайте** временные файлы
4. **Проверяйте размеры** загружаемых файлов

## 🆘 Экстренные действия

Если бот снова убит OOM Killer:

1. **Проверьте логи:**
   ```bash
   journalctl -u soroka --since "10 minutes ago"
   ```

2. **Уменьшите лимиты:**
   ```bash
   # В systemd конфигурации
   MemoryMax=1G
   MemoryHigh=800M
   ```

3. **Очистите временные файлы:**
   ```bash
   rm -rf temp/*
   ```

4. **Перезапустите с мониторингом:**
   ```bash
   sudo systemctl restart soroka
   python monitor_memory.py --interval 5
   ```

## 📊 Статистика

После применения исправлений вы должны увидеть:

- ✅ Отсутствие OOM событий в логах
- ✅ Стабильное использование памяти < 85%
- ✅ Автоматическая очистка при предупреждениях
- ✅ Корректная обработка больших файлов

## 🔧 Дополнительные настройки

### Для серверов с ограниченной памятью

```ini
# В systemd конфигурации
MemoryMax=1G
MemoryHigh=800M
MemorySwapMax=500M
```

### Для мощных серверов

```ini
# В systemd конфигурации
MemoryMax=4G
MemoryHigh=3G
MemorySwapMax=2G
```

### Настройка OOM Protection

```python
# В config.py можно настроить пороги
OOM_WARNING_THRESHOLD = 80.0  # 80% вместо 85%
OOM_CRITICAL_THRESHOLD = 90.0  # 90% вместо 95%
```

---

**🎯 Результат:** Ваш бот теперь защищен от OOM Killer и будет стабильно работать даже при обработке больших файлов!
