#!/usr/bin/env python3
"""
Скрипт для мониторинга использования памяти бота Soroka
"""

import os
import sys
import time
import psutil
import argparse
from datetime import datetime
from loguru import logger

# Добавляем src в путь для импортов
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

try:
    from src.performance.oom_protection import get_oom_protection
    OOM_PROTECTION_AVAILABLE = True
except ImportError:
    OOM_PROTECTION_AVAILABLE = False
    logger.warning("OOM Protection недоступна")


def get_memory_info():
    """Получить информацию о памяти"""
    system_memory = psutil.virtual_memory()
    
    # Ищем процесс бота
    bot_process = None
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if proc.info['cmdline'] and any('main.py' in cmd for cmd in proc.info['cmdline']):
                bot_process = proc
                break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    
    result = {
        "timestamp": datetime.now().isoformat(),
        "system": {
            "total_mb": round(system_memory.total / (1024 * 1024), 2),
            "available_mb": round(system_memory.available / (1024 * 1024), 2),
            "used_mb": round(system_memory.used / (1024 * 1024), 2),
            "percent": round(system_memory.percent, 2)
        },
        "bot_process": None
    }
    
    if bot_process:
        try:
            process_memory = bot_process.memory_info()
            result["bot_process"] = {
                "pid": bot_process.pid,
                "rss_mb": round(process_memory.rss / (1024 * 1024), 2),
                "vms_mb": round(process_memory.vms / (1024 * 1024), 2),
                "cpu_percent": bot_process.cpu_percent()
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            result["bot_process"] = {"error": "Не удалось получить информацию о процессе"}
    
    return result


def print_memory_status(memory_info):
    """Вывести статус памяти в консоль"""
    timestamp = memory_info["timestamp"]
    system = memory_info["system"]
    bot_process = memory_info["bot_process"]
    
    print(f"\n{'='*60}")
    print(f"Мониторинг памяти Soroka Bot - {timestamp}")
    print(f"{'='*60}")
    
    print(f"Системная память:")
    print(f"  Всего: {system['total_mb']:.1f} MB")
    print(f"  Использовано: {system['used_mb']:.1f} MB ({system['percent']:.1f}%)")
    print(f"  Доступно: {system['available_mb']:.1f} MB")
    
    if bot_process and "error" not in bot_process:
        print(f"\nПроцесс бота (PID: {bot_process['pid']}):")
        print(f"  RSS: {bot_process['rss_mb']:.1f} MB")
        print(f"  VMS: {bot_process['vms_mb']:.1f} MB")
        print(f"  CPU: {bot_process['cpu_percent']:.1f}%")
    elif bot_process and "error" in bot_process:
        print(f"\nПроцесс бота: {bot_process['error']}")
    else:
        print(f"\nПроцесс бота: не найден")
    
    # Определяем статус
    if system['percent'] >= 95:
        status = "🚨 КРИТИЧЕСКИЙ"
    elif system['percent'] >= 85:
        status = "⚠️  ВЫСОКИЙ"
    elif system['percent'] >= 70:
        status = "🟡 СРЕДНИЙ"
    else:
        status = "✅ НОРМАЛЬНЫЙ"
    
    print(f"\nСтатус: {status}")


def monitor_continuous(interval=10, max_iterations=None):
    """Непрерывный мониторинг памяти"""
    logger.info(f"Запуск непрерывного мониторинга памяти (интервал: {interval}с)")
    
    iteration = 0
    try:
        while True:
            if max_iterations and iteration >= max_iterations:
                break
                
            memory_info = get_memory_info()
            print_memory_status(memory_info)
            
            # Проверяем OOM защиту если доступна
            if OOM_PROTECTION_AVAILABLE:
                oom_protection = get_oom_protection()
                oom_stats = oom_protection.get_statistics()
                
                if oom_stats['oom_events_count'] > 0:
                    print(f"\n🚨 OOM события: {oom_stats['oom_events_count']}")
                if oom_stats['memory_warnings_count'] > 0:
                    print(f"⚠️  Предупреждения памяти: {oom_stats['memory_warnings_count']}")
            
            iteration += 1
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print(f"\n\nМониторинг остановлен пользователем")
    except Exception as e:
        logger.error(f"Ошибка при мониторинге: {e}")


def check_oom_protection():
    """Проверить статус OOM защиты"""
    if not OOM_PROTECTION_AVAILABLE:
        print("❌ OOM Protection недоступна")
        return
    
    oom_protection = get_oom_protection()
    stats = oom_protection.get_statistics()
    
    print(f"\n{'='*60}")
    print(f"Статус OOM Protection")
    print(f"{'='*60}")
    
    print(f"Защита активна: {'✅' if stats['protection_enabled'] else '❌'}")
    print(f"OOM события: {stats['oom_events_count']}")
    print(f"Предупреждения памяти: {stats['memory_warnings_count']}")
    print(f"События очистки: {stats['cleanup_events_count']}")
    
    memory_status = stats['current_memory_status']
    print(f"\nТекущий статус памяти:")
    print(f"  Система: {memory_status['system']['percent']:.1f}%")
    print(f"  Процесс: {memory_status['process']['rss_mb']:.1f} MB")
    print(f"  Статус: {memory_status['status']}")
    
    if stats['recent_events']['oom_events']:
        print(f"\nПоследние OOM события:")
        for event in stats['recent_events']['oom_events'][-3:]:
            print(f"  - {event['timestamp']}: {event['type']}")


def main():
    parser = argparse.ArgumentParser(description="Мониторинг памяти Soroka Bot")
    parser.add_argument("--interval", "-i", type=int, default=10, 
                       help="Интервал мониторинга в секундах (по умолчанию: 10)")
    parser.add_argument("--once", action="store_true", 
                       help="Показать статус один раз и выйти")
    parser.add_argument("--max-iterations", type=int, 
                       help="Максимальное количество итераций")
    parser.add_argument("--check-oom", action="store_true", 
                       help="Проверить статус OOM защиты")
    
    args = parser.parse_args()
    
    if args.check_oom:
        check_oom_protection()
    elif args.once:
        memory_info = get_memory_info()
        print_memory_status(memory_info)
    else:
        monitor_continuous(args.interval, args.max_iterations)


if __name__ == "__main__":
    main()
