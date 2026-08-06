"""Чистые билдеры административной поверхности (критика v9, ADR-0005).

Единый источник текста и клавиатур для команд и inline-кнопок админ-меню:
команда и её callback-двойник зовут один билдер, поэтому текст не расходится.
Разметка — Telegram HTML (статические теги пишем прямо, динамику экранируем
через :func:`src.ux.html_text.esc`). Эмодзи — только навигационный лексикон
Фаз 1–3; статусы и состояния называем словами, а не декоративными глифами.
"""

from typing import TYPE_CHECKING, Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.ux.html_text import esc
from src.ux.speaker_mapping_ui import SELECTED_MARK

if TYPE_CHECKING:  # только для аннотации: вид не тянет за собой модуль генерации
    from src.llm.protocol_generator import SchemaProbeVerdict

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
        "• <code>/add_model</code> — добавить модель\n"
        "• <code>/check_model</code> — применяет ли модель строгую схему\n\n"

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


def _sync_button() -> InlineKeyboardButton:
    """Синхронизация пресетов из .env — выход со списка в любом его состоянии."""
    return InlineKeyboardButton(
        text="Синхронизировать из .env",
        callback_data="admin_models_sync",
    )


def _preset_states(preset: dict, *, is_fallback: bool) -> str:
    """Состояния пресета в строке списка — словами, а не глифами."""
    states = []
    if not preset.get("is_enabled"):
        states.append("выкл")
    elif preset.get("admin_only"):
        states.append("админы")
    if is_fallback:
        states.append("резерв")
    return "".join(f" · {state}" for state in states)


def models_list_view(presets, *, active_key: Optional[str],
                     fallback_key: Optional[str]) -> tuple[str, InlineKeyboardMarkup]:
    """Список пресетов модели (единый источник /models и его inline-двойника).

    Активный пресет помечается маркером выбора (канон v10: ✓ значит «выбрано»,
    ✅ — «сделано»); состояние (выключен / только админы / резерв) называем
    словом, а не декоративным глифом. Резерв — второй выбор, но тем же маркером
    его не метят: два одинаковых знака в списке перестают отвечать на вопрос
    «а активный-то какой».
    """
    if not presets:
        text = ("<b>Список моделей</b>\n\n"
                "Моделей пока нет. Используйте /add_model или синхронизируйте из .env.")
        return text, InlineKeyboardMarkup(inline_keyboard=[[_sync_button()]])

    lines = ["<b>Список моделей</b>\n"]
    buttons = []
    for preset in presets:
        prefix = f"{SELECTED_MARK} " if preset["key"] == active_key else ""
        suffix = _preset_states(preset, is_fallback=preset["key"] == fallback_key)
        lines.append(f"{prefix}{esc(preset['name'])}{suffix}")
        buttons.append([InlineKeyboardButton(
            text=f"{prefix}{preset['name']}{suffix}",
            callback_data=f"admin_model_{preset['key']}",
        )])

    buttons.append([_sync_button()])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons)


def _fallback_label(*, is_fallback: bool, is_active: bool) -> str:
    """Строка «Резервная» в карточке.

    Резерв, совпавший с активным пресетом, — законное состояние (сюда приводит
    сам автовозврат), но переключаться ему уже некуда: говорим это словами,
    чтобы карточка не обещала автовозврат, которого не будет.
    """
    if is_fallback and is_active:
        return "да (совпадает с активной — автовозврата не будет)"
    return "да" if is_fallback else "—"


def _model_detail_text(preset: dict, *, is_active: bool, is_fallback: bool) -> str:
    """Текст карточки: адрес пресета целиком и его роль в настройках."""
    api_key_status = "задан" if preset.get("api_key") else "не задан"
    enabled_label = "включена" if preset.get("is_enabled") else "выключена"
    access_label = "только админы" if preset.get("admin_only") else "все пользователи"
    return (
        f"<b>{esc(preset['name'])}</b>\n\n"
        f"Key: <code>{esc(preset['key'])}</code>\n"
        f"Model ID: <code>{esc(preset['model'])}</code>\n"
        f"Base URL: <code>{esc(preset['base_url'])}</code>\n"
        f"API Key: {api_key_status}\n"
        f"Статус: {enabled_label}\n"
        f"Доступ: {access_label}\n"
        f"Активная: {'да' if is_active else '—'}\n"
        f"Резервная: {_fallback_label(is_fallback=is_fallback, is_active=is_active)}"
    )


def _model_detail_keyboard(preset: dict, *, is_active: bool,
                           is_fallback: bool) -> InlineKeyboardMarkup:
    """Кнопки карточки: действия, доступные пресету в его нынешней роли."""
    key = preset["key"]
    rows = []
    if not is_active and preset.get("is_enabled"):
        rows.append([InlineKeyboardButton(
            text="Сделать активной",
            callback_data=f"set_active_model_{key}",
        )])
    rows.extend([
        [
            InlineKeyboardButton(
                text="Выключить" if preset.get("is_enabled") else "Включить",
                callback_data=f"admin_model_toggle_{key}",
            ),
            InlineKeyboardButton(
                text="Для всех" if preset.get("admin_only") else "Только админы",
                callback_data=f"admin_model_access_{key}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="Убрать из резервных" if is_fallback else "Сделать резервной",
                callback_data=f"admin_model_reserve_{key}",
            ),
        ],
        [
            InlineKeyboardButton(text="Удалить", callback_data=f"admin_model_delete_{key}"),
            InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_models_list"),
        ],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def model_detail_view(preset: dict, *, active_key: Optional[str],
                      fallback_key: Optional[str]) -> tuple[str, InlineKeyboardMarkup]:
    """Карточка одного пресета модели (единый источник детального экрана).

    Роль пресета вид не выясняет сам: активный и резервный ключи — настройки
    приложения, и ходить за ними из вида значило бы завести в нём базу.
    """
    is_active = preset["key"] == active_key
    is_fallback = preset["key"] == fallback_key
    return (
        _model_detail_text(preset, is_active=is_active, is_fallback=is_fallback),
        _model_detail_keyboard(preset, is_active=is_active, is_fallback=is_fallback),
    )


def _checked_address(preset_name: str, model: str, base_url: Optional[str]) -> str:
    """Кого проверяли: без модели и адреса вердикт не отличить от чужого."""
    return (
        f"Пресет: {esc(preset_name)}\n"
        f"Модель: <code>{esc(model)}</code>\n"
        f"Адрес: <code>{esc(base_url or 'по умолчанию')}</code>"
    )


def model_check_verdict(preset_name: str, verdict: "SchemaProbeVerdict") -> str:
    """Вердикт зонда строгих схем (единый источник /check_model, ADR-0007).

    Схему, принятую и выброшенную, помечаем ⚠️, а не ❌: провайдер ответил
    успешно и сам по себе жив — непригодна для протоколов именно модель.
    """
    if verdict.schema_honored:
        headline = "✅ Схема применяется"
        note = (
            "Модель вернула ровно затребованные ключи — контракт ответа она "
            "соблюдает, можно отдавать в работу."
        )
    else:
        returned = ", ".join(verdict.returned_keys) or "ни одного"
        headline = "⚠️ Схема принята и выброшена"
        note = (
            f"Ответ успешен и валиден, но ключи в нём свои: <code>{esc(returned)}</code>.\n"
            "Такой отказ бесшумен — протокол потеряет разделы молча. "
            "Выберите другую модель: /models."
        )
    return (
        "<b>Проверка модели</b>\n\n"
        f"{headline}\n\n"
        f"{_checked_address(preset_name, verdict.model, verdict.base_url)}\n\n"
        f"{note}"
    )


def model_check_failed(preset_name: str, model: str, base_url: Optional[str],
                       reason: str, *, key_refused: bool) -> str:
    """Зонд не дошёл до модели: это не вердикт о схеме (единый источник)."""
    if key_refused:
        headline = "❌ Ключ не принят провайдером"
        step = "Задайте пресету рабочий ключ через /add_model и повторите /check_model."
    else:
        headline = "❌ Провайдер не ответил"
        step = "Проверьте адрес и доступность провайдера, затем повторите /check_model."
    return (
        "<b>Проверка модели</b>\n\n"
        f"{headline}\n\n"
        f"{_checked_address(preset_name, model, base_url)}\n\n"
        "Вердикта о схеме нет: до модели не дошли.\n"
        f"{step}\n\n"
        f"Причина: <code>{esc(reason)}</code>"
    )
