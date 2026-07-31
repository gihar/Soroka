"""
Конструктор красивых и информативных сообщений для пользователей
"""

from typing import Any, Dict

# Формулировки, которые нужны нескольким экранам сразу. Живут здесь по одному
# разу: пока текст размножен по четырнадцати местам, следующая правка голоса
# неизбежно поправит тринадцать из них (критика v10).
TEMPLATES_LOAD_FAILED = (
    "❌ Не удалось загрузить шаблоны.\n"
    "Откройте /templates ещё раз."
)

TEMPLATES_EMPTY = (
    "<b>Шаблоны не найдены</b>\n\n"
    "Обратитесь к администратору."
)

PROTOCOL_GONE = "Протокол не найден — возможно, история очищена."


class MessageBuilder:
    """Строитель красивых сообщений"""

    @classmethod
    def welcome_message(cls) -> str:
        """Приветствие: одна фраза о сути, точка входа, команды."""
        return (
            "<b>Превращаю записи встреч в протоколы</b>\n\n"
            "Отправьте аудио, видео или ссылку на запись — в ответ придёт "
            "структурированный протокол: решения, задачи и сроки, блокеры.\n\n"
            "/templates — шаблоны протокола\n"
            "/settings — формат вывода и сопоставление спикеров\n"
            "/help — справка и ограничения"
        )

    @classmethod
    def help_message(cls) -> str:
        """Справка: реальный флоу с меню, форматы, лимиты, шаблоны."""
        return (
            "<b>Как получить протокол</b>\n"
            "1. Отправьте запись: аудио, видео, голосовое, видеозаметку "
            "или ссылку на Google Drive / Яндекс.Диск / Synology Drive.\n"
            "2. В меню выберите «Быстрая обработка» — умный шаблон и "
            "сохранённые настройки — или «Настроить»: участники и шаблон.\n"
            "3. Протокол придёт сообщениями; файл .md, PDF или Word — "
            "в /settings.\n\n"
            "<b>Форматы</b>\n"
            "Аудио: MP3, WAV, M4A, OGG, FLAC. Видео: MP4, AVI, MOV, MKV, WebM.\n\n"
            "<b>Ограничения</b>\n"
            "Файл в Telegram — до 20 МБ; по ссылке на облако — до 2 ГБ. "
            "Рекомендуемая длительность — до 60 минут.\n\n"
            "<b>Шаблоны</b>\n"
            "Подбираются автоматически по содержанию встречи; выбрать вручную "
            "или создать свой — /templates."
        )
    
    # Голос ошибки (эталон result_sender): одно простое предложение + следующий
    # шаг. Технические детали (тип, exception-текст) уходят в логи, не в чат.
    _ERROR_VOICE = {
        "file_size": (
            "❌ Файл слишком большой.\n"
            "Сожмите его или пришлите ссылку на облако — "
            "Google Drive, Яндекс.Диск, Synology Drive."
        ),
        "file_format": (
            "❌ Этот формат не поддерживается.\n"
            "Пришлите аудио (MP3, WAV, M4A, OGG) или видео (MP4, MOV, MKV)."
        ),
        "processing": (
            "❌ Не получилось обработать запись.\n"
            "Отправьте её ещё раз — обычно повторная попытка помогает."
        ),
        "network": (
            "❌ Сервис не ответил.\n"
            "Повторите попытку через пару минут."
        ),
        "rate_limit": (
            "❌ Слишком много запросов подряд.\n"
            "Подождите минуту и повторите."
        ),
        "service_unavailable": (
            "❌ Сервис временно недоступен.\n"
            "Повторите попытку через 10–15 минут."
        ),
    }

    _ERROR_DEFAULT = (
        "❌ Не получилось обработать запрос.\n"
        "Попробуйте ещё раз — если повторится, отправьте запись заново."
    )

    @classmethod
    def error_message(cls, error_type: str, details: str = "") -> str:
        """Короткое сообщение об ошибке: что не получилось + следующий шаг.

        Внутренний код ошибки и exception-текст пользователю не показываются —
        они уходят в лог. Незнакомый тип получает честный общий текст.
        """
        if details:
            from loguru import logger
            logger.info("error_message: тип={} детали={}", error_type, details)

        return cls._ERROR_VOICE.get(error_type, cls._ERROR_DEFAULT)

    @classmethod
    def processing_complete_message(cls, result: Dict[str, Any]) -> str:
        """Короткая сводка над протоколом (Telegram HTML, 3-4 строки).

        Сводка пересылается вместе с протоколом, поэтому несёт только то,
        что нужно читателю: статус, шаблон, участники, время. Технические
        детали (модель, объём текста, сжатие) уходят в логи.
        """
        import html as _html


        cls._log_processing_details(result)

        lines = ["\u2705 <b>Протокол готов</b>"]

        template_name = (result.get("template_used") or {}).get("name")
        if template_name:
            lines.append(f"Шаблон: {_html.escape(template_name)}")

        participants_line = cls._participants_line(result)
        if participants_line:
            lines.append(participants_line)

        duration = result.get("processing_duration")
        if duration:
            lines.append(f"Обработка: {cls._format_duration(duration)}")

        notes = cls._document_notes(result)
        if notes:
            # Пустая строка отделяет «что это» от «что с этим не так»: сводка
            # остаётся сканируемой, оговорки не сливаются со статусом.
            lines.append("")
            lines.extend(notes)

        return "\n".join(lines)

    @staticmethod
    def _document_notes(result: Dict[str, Any]) -> list:
        """Оговорки о документе — в сводку ПЕРЕД протоколом, не после него.

        Раньше они уходили отдельными пузырями после тела, и каждый прогон
        заканчивался сомнением в вещи, которую пользователь сейчас перешлёт. В
        режимах ``pdf``/``docx`` такой пузырь вдобавок оставался в чате и с
        файлом не ехал — читатель «наверху» получал поручения «Участнику N» без
        объяснения. Сводка пересылается вместе с протоколом, поэтому место
        оговорки здесь.
        """
        notes = list(result.get("warnings") or [])
        # В файловых режимах сводка остаётся в чате и с документом не едет —
        # там оговорка о дате вписана в само тело (критика v11), и повторять её
        # здесь значит показать её тому, кто и так её видит, и не показать тому,
        # кому переслали файл.
        in_chat = (result.get("protocol_output_mode") or "messages") == "messages"
        if result.get("date_is_assumed") and in_chat:
            notes.append(
                "📅 Дата в шапке — день обработки: в записи её не нашлось. "
                "Поправить: кнопка «Дата и название» под протоколом."
            )
        return notes

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """«5 мин 12 с» читается легче, чем «312 с»."""
        total = int(round(seconds))
        minutes, secs = divmod(total, 60)
        if minutes and secs:
            return f"{minutes} мин {secs} с"
        if minutes:
            return f"{minutes} мин"
        return f"{secs} с"

    @staticmethod
    def _participants_line(result: Dict[str, Any]) -> str:
        """Строка об участниках: сопоставление или количество голосов."""
        speaker_mapping = result.get("speaker_mapping") or {}
        if speaker_mapping:
            return f"Участников сопоставлено: {len(speaker_mapping)}"
        diarization = (result.get("transcription_result") or {}).get("diarization")
        if diarization and len(getattr(diarization, "speakers", [])) > 1:
            return f"Участников: {len(diarization.speakers)}"
        return ""

    @staticmethod
    def _log_processing_details(result: Dict[str, Any]) -> None:
        """Технические детали обработки — в логи, не в чат."""
        from loguru import logger

        transcription = (result.get("transcription_result") or {}).get("transcription") or ""
        compression = (result.get("transcription_result") or {}).get("compression_info") or {}
        logger.info(
            "Обработка завершена: шаблон={}, модель={}, текст={} символов, сжатие={}",
            (result.get("template_used") or {}).get("name"),
            result.get("llm_model_name") or result.get("llm_provider_used"),
            len(transcription),
            compression.get("compression_ratio"),
        )

    @classmethod
    def file_validation_error(cls, error_details: Dict[str, Any]) -> str:
        """Сообщение об ошибке валидации файла"""
        error_type = error_details.get("type", "unknown")
        
        if error_type == "size":
            actual_size = error_details.get("actual_size", 0)
            max_size = error_details.get("max_size", 20)
            actual_mb = actual_size / (1024 * 1024)
            
            # Варианты действий не противоречат ошибке: авто-сжатие как «выход»
            # убрано — файл и так превысил лимит до обработки.
            return (
                "❌ Файл слишком большой.\n"
                f"Сейчас {actual_mb:.1f} МБ, а максимум — {max_size} МБ.\n\n"
                "Что можно сделать:\n"
                "• Пришлите ссылку на облако (Google Drive, Яндекс.Диск, Synology Drive)\n"
                "• Разделите запись на части\n"
                "• Сохраните в формате с более сильным сжатием (MP3)"
            )

        elif error_type == "format":
            import html as _html

            file_ext = error_details.get("extension", "")
            supported_formats = error_details.get("supported_formats", {})

            audio = ", ".join(supported_formats.get("audio", []))
            video = ", ".join(supported_formats.get("video", []))
            return (
                "❌ Этот формат не поддерживается.\n"
                f"Файл: {_html.escape(str(file_ext), quote=False)}\n\n"
                "Пришлите запись в одном из форматов:\n"
                f"• Аудио: {audio}\n"
                f"• Видео: {video}"
            )

        return cls.error_message("validation", str(error_details))
    
    @classmethod
    def templates_help_message(cls) -> str:
        """Справка по работе с шаблонами.

        Документирует Markdown-синтаксис шаблонов протокола (ADR-0001): примеры
        синтаксиса (``**жирный**``, ``#``, переменные) намеренно остаются
        БУКВАЛЬНЫМ текстом внутри ``<code>``/``<pre>`` — так пользователь видит,
        что писать. Заголовки самой справки — обычный <b> Telegram HTML.
        """
        return (
            "<b>Шаблоны протокола</b>\n"
            "Шаблон задаёт структуру протокола: какие секции и в каком порядке.\n\n"

            # Переменные сгруппированы по смыслу, а не перечислены восемью
            # строками: шапка, суть встречи, детали (правило ≤4 групп).
            "<b>Переменные:</b>\n"
            "• Шапка: <code>{{ meeting_title }}</code>, <code>{{ date }}</code>, "
            "<code>{{ participants }}</code>\n"
            "• Главное: <code>{{ decisions }}</code>, "
            "<code>{{ action_items }}</code>\n"
            "• Детали: <code>{{ risks_and_blockers }}</code>, "
            "<code>{{ discussion }}</code>\n\n"

            "<b>Условные секции:</b>\n"
            "Секция в <code>{% if переменная %}</code> … <code>{% endif %}</code> "
            "не попадёт в протокол, если данных нет.\n\n"

            "<b>Пример:</b>\n"
            "<pre>"
            "# {{ meeting_title or 'Протокол встречи' }}\n"
            "{% if date %}**Дата:** {{ date }}{% endif %}\n"
            "{% if participants %}**Участники:** {{ participants }}{% endif %}\n\n"
            "{% if decisions %}\n"
            "## Решения\n"
            "{{ decisions }}\n"
            "{% endif %}"
            "</pre>\n"
            "Разметка — Markdown: <code>#</code>, <code>-</code>, "
            "<code>**жирный**</code>."
        )
