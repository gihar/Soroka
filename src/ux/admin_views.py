"""Чистые билдеры административной поверхности (критика v9, ADR-0005).

Единый источник текста и клавиатур для команд и inline-кнопок админ-меню:
команда и её callback-двойник зовут один билдер, поэтому текст не расходится.
Разметка — Telegram HTML (статические теги пишем прямо, динамику экранируем
через :func:`src.ux.html_text.esc`). Эмодзи — только навигационный лексикон
Фаз 1–3; статусы и состояния называем словами, а не декоративными глифами.
"""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.ux.html_text import esc
from src.ux.speaker_mapping_ui import SELECTED_MARK

# Отказ в доступе был размножен по четырнадцати местам админской поверхности
# (критика v10). Одна формулировка — одно место.
ACCESS_DENIED = "❌ Недостаточно прав для выполнения команды."

# Статус здоровья компонента → лексиконный глиф (один глиф = одно значение).
_HEALTH_GLYPH = {
    "healthy": "✅",
    "degraded": "⚠️",
    "unhealthy": "❌",
    "unknown": "❓",
}

# Режимы транскрипции: подпись кнопки и человекочитаемое описание.
_TRANSCRIPTION_MODES = (
    ("local", "Локальная (Whisper)", "Локальная транскрипция через Whisper"),
    ("cloud", "Облачная (Groq)", "Облачная транскрипция через Groq API"),
    ("hybrid", "Гибридная (Groq + диаризация)",
     "Гибридная: облачная транскрипция + локальная диаризация"),
    ("speechmatics", "Speechmatics",
     "Транскрипция и диаризация через Speechmatics API"),
    ("deepgram", "Deepgram", "Транскрипция и диаризация через Deepgram API"),
    ("leopard", "Leopard (Picovoice)",
     "Локальная транскрипция через Picovoice Leopard"),
)


def admin_help_text() -> str:
    """Справка по административным командам (единый источник /admin_help)."""
    return (
        "<b>Административные команды</b>\n\n"

        "<b>Мониторинг</b>\n"
        "• <code>/status</code> — общий статус системы\n"
        "• <code>/health</code> — детальная проверка здоровья\n"
        "• <code>/stats</code> — детальная статистика\n"
        "• <code>/export_stats</code> — экспорт статистики в JSON\n\n"

        "<b>Производительность</b>\n"
        "• <code>/performance</code> — статистика производительности\n"
        "• <code>/optimize</code> — принудительная оптимизация памяти\n\n"

        "<b>Управление</b>\n"
        "• <code>/reset_reliability</code> — сброс компонентов надежности\n"
        "• <code>/transcription_mode</code> — переключение режима транскрипции\n\n"

        "<b>Управление моделями</b>\n"
        "• <code>/models</code> — список моделей с inline-управлением\n"
        "• <code>/add_model</code> — добавить модель\n\n"

        "<b>Очистка файлов</b>\n"
        "• <code>/cleanup</code> — статистика файлов и настройки очистки\n"
        "• <code>/cleanup_force</code> — принудительная очистка временных файлов\n\n"

        "<b>Справка</b>\n"
        "• <code>/admin_help</code> — эта справка\n\n"

        "Команды доступны только авторизованным пользователям."
    )


def performance_report(cache_stats: dict, memory_stats: dict,
                       task_stats: dict, metrics_stats: dict) -> str:
    """Отчёт производительности (единый источник /performance)."""
    current = memory_stats["current_memory"]
    processing = metrics_stats["processing"]
    optimizing = "Вкл" if memory_stats["is_optimizing"] else "Выкл"
    return (
        "<b>Статистика производительности</b>\n\n"

        "<b>Кэш</b>\n"
        f"• Hit Rate: {cache_stats['hit_rate_percent']}%\n"
        f"• Память: {cache_stats['memory_usage_mb']} МБ "
        f"({cache_stats['memory_usage_percent']}%)\n"
        f"• Записей: {cache_stats['memory_entries']} + "
        f"{cache_stats['disk_entries']} (диск)\n\n"

        "<b>Память</b>\n"
        f"• Система: {current['percent']}%\n"
        f"• Процесс: {current['process_mb']:.1f} МБ\n"
        f"• Автооптимизация: {optimizing}\n\n"

        "<b>Задачи</b>\n"
        f"• Активные: {task_stats['active_tasks']}\n"
        f"• Макс параллельно: {task_stats['max_concurrent']}\n"
        f"• Успешность: {task_stats['success_rate']:.1f}%\n\n"

        "<b>Обработка</b>\n"
        f"• Запросов за час: {processing['requests_1h']}\n"
        f"• Успешность: {processing['success_rate_percent']}%\n"
        f"• Среднее время: {processing['avg_duration_seconds']}с\n"
        f"• Эффективность: {processing['avg_efficiency_ratio']}"
    )


def cleanup_stats_report(stats: dict, *, interval_minutes: int,
                         temp_max_age_hours: int, cache_max_age_hours: int,
                         cleanup_enabled: bool) -> str:
    """Статистика файлов и настройки очистки (единый источник /cleanup)."""
    auto = "включена" if cleanup_enabled else "выключена"
    return (
        "<b>Статистика файлов</b>\n\n"
        f"Временные файлы: {stats['temp_files']} ({stats['temp_size_mb']:.1f} МБ)\n"
        f"Кэш файлы: {stats['cache_files']} ({stats['cache_size_mb']:.1f} МБ)\n\n"
        f"Старые временные файлы: {stats['old_temp_files']}\n"
        f"Старые кэш файлы: {stats['old_cache_files']}\n\n"
        "<b>Настройки</b>\n"
        f"• Интервал очистки: {interval_minutes} мин\n"
        f"• Макс. возраст временных файлов: {temp_max_age_hours} ч\n"
        f"• Макс. возраст кэш файлов: {cache_max_age_hours} ч\n"
        f"• Автоочистка: {auto}\n\n"
        "Используйте /cleanup_force для принудительной очистки"
    )


def cleanup_done_report(cleaned_count: int, stats: dict) -> str:
    """Результат принудительной очистки (единый источник /cleanup_force)."""
    return (
        "✅ <b>Очистка завершена</b>\n\n"
        f"Удалено файлов: {cleaned_count}\n\n"
        "<b>Текущее состояние</b>\n"
        f"• Временные файлы: {stats['temp_files']} ({stats['temp_size_mb']:.1f} МБ)\n"
        f"• Кэш файлы: {stats['cache_files']} ({stats['cache_size_mb']:.1f} МБ)"
    )


def health_report(results: dict) -> str:
    """Детальная проверка здоровья (единый источник /health).

    ``results`` — отображение имя_компонента → объект с ``.status.value``,
    ``.message`` и ``.response_time`` (как отдаёт health_checker.check_all()).
    """
    blocks = ["<b>Проверка здоровья</b>"]
    for component, result in results.items():
        status = result.status.value
        glyph = _HEALTH_GLYPH.get(status, "❓")
        detail = esc(result.message)
        if result.response_time:
            detail = f"{detail} · {result.response_time:.3f}с"
        blocks.append(
            f"{glyph} <b>{esc(component)}</b> — {esc(status)}\n{detail}"
        )
    return "\n\n".join(blocks)


def transcription_mode_view(current_mode: str) -> tuple[str, InlineKeyboardMarkup]:
    """Текст и клавиатура выбора режима транскрипции (единый источник)."""
    rows = []
    description = "Неизвестный режим"
    for mode, label, mode_description in _TRANSCRIPTION_MODES:
        if mode == current_mode:
            description = mode_description
        prefix = f"{SELECTED_MARK} " if mode == current_mode else ""
        rows.append([InlineKeyboardButton(
            text=f"{prefix}{label}",
            callback_data=f"set_transcription_mode_{mode}",
        )])

    text = (
        "<b>Режим транскрипции</b>\n\n"
        f"Текущий: {esc(current_mode)}\n"
        f"{esc(description)}\n\n"
        "Выберите новый режим:"
    )
    return text, InlineKeyboardMarkup(inline_keyboard=rows)
