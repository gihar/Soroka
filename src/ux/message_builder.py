"""
Конструктор красивых и информативных сообщений для пользователей
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.utils.message_utils import escape_markdown


@dataclass
class MessageStyle:
    """Стиль сообщения"""
    emoji: str
    title: str
    color: str = "info"  # info, success, warning, error


class MessageBuilder:
    """Строитель красивых сообщений"""
    
    # Стили для разных типов сообщений
    STYLES = {
        "welcome": MessageStyle("🤖", "Добро пожаловать!", "info"),
        "processing": MessageStyle("🔄", "Обработка", "info"),
        "success": MessageStyle("✅", "Успешно", "success"),
        "error": MessageStyle("❌", "Ошибка", "error"),
        "warning": MessageStyle("⚠️", "Внимание", "warning"),
        "info": MessageStyle("ℹ️", "Информация", "info"),
        "help": MessageStyle("❓", "Справка", "info"),
        "settings": MessageStyle("⚙️", "Настройки", "info"),
        "templates": MessageStyle("📝", "Шаблоны", "info"),
        "stats": MessageStyle("📊", "Статистика", "info"),
    }
    
    @classmethod
    def welcome_message(cls) -> str:
        """Приветственное сообщение"""
        return (
            "🤖 **Добро пожаловать в бота для создания протоколов встреч!**\n\n"
            "📋 **Что я умею:**\n"
            "• 🎵 Обрабатывать аудио записи встреч\n"
            "• 🎬 Анализировать видео файлы\n"
            "• 👥 Определять говорящих\n"
            "• 📝 Создавать структурированные протоколы\n"
            "• 🎨 Использовать готовые и кастомные шаблоны\n\n"
            "🚀 **Как начать:**\n"
            "1. Отправьте аудио или видео файл, либо ссылку на файл\n"
            "2. Выберите шаблон протокола\n"
            "3. Получите готовый документ!\n\n"
            "💡 **Полезные команды:**\n"
            "• /help - подробная справка\n"
            "• /templates - управление шаблонами\n"
            "• /settings - настройки ИИ\n\n"
            "📤 **Просто отправьте файл, чтобы начать!**"
        )
    
    @classmethod
    def help_message(cls) -> str:
        """Подробная справка"""
        return (
            "🆘 **Справка по использованию бота**\n\n"
            
            "📱 **Поддерживаемые форматы:**\n"
            "🎵 Аудио: MP3, WAV, M4A, OGG, FLAC\n"
            "🎬 Видео: MP4, AVI, MOV, MKV, WebM\n"
            "🎤 Голосовые сообщения и видеозаметки\n\n"
            
            "⚡ **Быстрый старт:**\n"
            "1. 📤 Отправьте файл\n"
            "2. 📝 Выберите шаблон (или используйте автовыбор)\n"
            "3. 🤖 Выберите ИИ (или оставьте автовыбор)\n"
            "4. 📋 Получите готовый протокол!\n\n"
            
            "📝 **Шаблоны протоколов:**\n"
            "• Встроенные шаблоны: универсальный, деловой, техническая встреча и др.\n"
            "• Автоматический выбор подходящего шаблона по содержанию\n"
            "• Создавайте свои шаблоны через /templates\n\n"
            
            "⚙️ **Настройки:**\n"
            "• /settings - выбор предпочитаемого ИИ\n"
            "• /templates - управление шаблонами\n\n"
            
            "🔒 **Ограничения:**\n"
            "• Макс. размер файла: 20MB\n"
            "• Рекомендуемая длительность: до 60 минут\n"
            "• Система автоматически оптимизирует файлы\n\n"
            
            "❓ **Вопросы?** Просто отправьте файл и следуйте инструкциям!"
        )
    
    @classmethod
    def error_message(cls, error_type: str, details: str = "", 
                     suggestions: Optional[List[str]] = None) -> str:
        """Сообщение об ошибке с рекомендациями"""
        message = "❌ **Произошла ошибка**\n\n"
        
        # Тип ошибки
        error_types = {
            "file_size": "Размер файла превышает лимит",
            "file_format": "Неподдерживаемый формат файла", 
            "processing": "Ошибка при обработке файла",
            "network": "Ошибка сети или сервиса",
            "validation": "Ошибка валидации данных",
            "permission": "Недостаточно прав",
            "rate_limit": "Превышен лимит запросов",
            "service_unavailable": "Сервис временно недоступен"
        }
        
        error_title = error_types.get(error_type, "Неизвестная ошибка")
        message += f"**Тип:** {error_title}\n"
        
        if details:
            message += f"**Детали:** {details}\n"
        
        message += "\n"
        
        # Рекомендации по типу ошибки
        if not suggestions:
            suggestions = cls._get_default_suggestions(error_type)
        
        if suggestions:
            message += "💡 **Что можно сделать:**\n"
            for suggestion in suggestions:
                message += f"• {suggestion}\n"
            message += "\n"
        
        message += "🔄 Попробуйте еще раз или обратитесь за помощью командой /help"
        
        return message
    
    @classmethod
    def _get_default_suggestions(cls, error_type: str) -> List[str]:
        """Получить стандартные рекомендации по типу ошибки"""
        suggestions_map = {
            "file_size": [
                "Сжмите файл или разделите на части",
                "Используйте формат с лучшим сжатием (MP3 вместо WAV)",
                "Максимальный размер: 20MB"
            ],
            "file_format": [
                "Используйте поддерживаемые форматы: MP3, WAV, M4A, MP4",
                "Конвертируйте файл в один из поддерживаемых форматов",
                "Отправьте файл как документ, если как медиа не работает"
            ],
            "processing": [
                "Проверьте качество аудио (четкость речи)",
                "Убедитесь, что файл не поврежден",
                "Попробуйте загрузить файл повторно"
            ],
            "network": [
                "Проверьте интернет-соединение",
                "Повторите попытку через несколько минут",
                "Используйте другую сеть если возможно"
            ],
            "rate_limit": [
                "Подождите несколько минут перед следующей попыткой",
                "Обрабатывайте файлы по одному",
                "Избегайте частых запросов"
            ],
            "service_unavailable": [
                "Сервис временно недоступен",
                "Повторите попытку через 10-15 минут",
                "Проверьте статус системы командой /status"
            ]
        }
        
        return suggestions_map.get(error_type, [
            "Попробуйте еще раз через несколько минут",
            "Обратитесь за помощью командой /help"
        ])
    
    @classmethod
    def processing_complete_message(cls, result: Dict[str, Any]) -> str:
        """Сообщение о завершении обработки"""
        message = "🎉 **Протокол успешно создан!**\n\n"
        
        # Основная информация
        message += "📋 **Результат обработки:**\n"
        
        if result.get("template_used"):
            template_name = result["template_used"].get("name", "Неизвестный")
            template_name = escape_markdown(template_name)
            message += f"📝 Шаблон: {template_name}\n"
        
        # Показываем человекочитаемое имя модели, если доступно
        if result.get("llm_model_name") or result.get("llm_model_used") or result.get("llm_provider_used"):
            ai_name = result.get("llm_model_name") or result.get("llm_model_used") or result.get("llm_provider_used")
            ai_name = escape_markdown(ai_name)
            message += f"🤖 ИИ: {ai_name}\n"
        
        # Информация о транскрипции (с ограничением длины)
        if result.get("transcription_result"):
            transcription = result["transcription_result"]
            if transcription.get("transcription"):
                char_count = len(transcription["transcription"])
                word_count = len(transcription["transcription"].split())
                message += f"📄 Текст: {char_count} символов, ~{word_count} слов\n"
            
            # Информация о сжатии файла (показывается только если не было показано ранее)
            if transcription.get("compression_info"):
                compression = transcription["compression_info"]
                if compression.get("compressed", False) and not compression.get("shown_during_processing", False):
                    original_mb = compression.get("original_size_mb", 0)
                    compressed_mb = compression.get("compressed_size_mb", 0)
                    ratio = compression.get("compression_ratio", 0)
                    saved_mb = compression.get("compression_saved_mb", 0)
                    
                    message += f"🗜️ Сжатие: {original_mb:.1f}MB → {compressed_mb:.1f}MB (экономия {ratio:.1f}%, -{saved_mb:.1f}MB)\n"
        
        # Информация о сопоставлении участников
        speaker_mapping = result.get("speaker_mapping", {})
        if speaker_mapping:
            message += "\n👥 **Участники:**\n"
            # Сортируем по speaker_id для предсказуемого порядка
            sorted_mapping = sorted(speaker_mapping.items())
            for speaker_id, participant_name in sorted_mapping:
                speaker_id_escaped = escape_markdown(speaker_id)
                participant_name_escaped = escape_markdown(participant_name)
                message += f"• {speaker_id_escaped} → {participant_name_escaped}\n"
        elif result.get("transcription_result", {}).get("diarization"):
            # Если нет сопоставления, показываем информацию о количестве спикеров
            diarization = result["transcription_result"]["diarization"]
            speakers_count = diarization.get("total_speakers", 0)
            if speakers_count > 1:
                message += f"\n👥 Участников: {speakers_count}\n"
        
        message += "\n"
        
        # Время обработки
        if result.get("processing_duration"):
            duration = result["processing_duration"]
            message += f"⏱️ Время обработки: {duration:.1f} сек\n"
        
        message += "\n📄 **Протокол отправляется ниже...**"
        
        # Проверяем, что сообщение не превышает лимит Telegram
        if len(message) > 4000:  # Оставляем запас для безопасности
            # Создаем сокращенную версию
            message = "🎉 **Протокол успешно создан!**\n\n"
            message += "📋 **Результат обработки:**\n"
            
            if result.get("template_used"):
                template_name = result["template_used"].get("name", "Неизвестный")
                template_name = escape_markdown(template_name)
                message += f"📝 Шаблон: {template_name}\n"
            
            if result.get("llm_model_name") or result.get("llm_model_used") or result.get("llm_provider_used"):
                ai_name = result.get("llm_model_name") or result.get("llm_model_used") or result.get("llm_provider_used")
                ai_name = escape_markdown(ai_name)
                message += f"🤖 ИИ: {ai_name}\n"
            
            if result.get("transcription_result", {}).get("transcription"):
                char_count = len(result["transcription_result"]["transcription"])
                word_count = len(result["transcription_result"]["transcription"].split())
                message += f"📄 Текст: {char_count} символов, ~{word_count} слов\n"
            
            # Информация о сжатии файла (сокращенная версия)
            if result.get("transcription_result", {}).get("compression_info"):
                compression = result["transcription_result"]["compression_info"]
                if compression.get("compressed", False):
                    original_mb = compression.get("original_size_mb", 0)
                    compressed_mb = compression.get("compressed_size_mb", 0)
                    ratio = compression.get("compression_ratio", 0)
                    message += f"🗜️ Сжатие: {original_mb:.1f}MB → {compressed_mb:.1f}MB ({ratio:.1f}%)\n"
            
            # Информация о сопоставлении участников (сокращенная версия)
            speaker_mapping = result.get("speaker_mapping", {})
            if speaker_mapping:
                message += "\n👥 **Участники:**\n"
                sorted_mapping = sorted(speaker_mapping.items())
                for speaker_id, participant_name in sorted_mapping:
                    speaker_id_escaped = escape_markdown(speaker_id)
                    participant_name_escaped = escape_markdown(participant_name)
                    message += f"• {speaker_id_escaped} → {participant_name_escaped}\n"
            elif result.get("transcription_result", {}).get("diarization"):
                diarization = result["transcription_result"]["diarization"]
                speakers_count = diarization.get("total_speakers", 0)
                if speakers_count > 1:
                    message += f"\n👥 Участников: {speakers_count}\n"
            
            message += "\n"
            
            if result.get("processing_duration"):
                duration = result["processing_duration"]
                message += f"⏱️ Время обработки: {duration:.1f} сек\n"
            
            message += "\n📄 **Протокол отправляется ниже...**"
        
        return message
    
    @classmethod
    def file_validation_error(cls, error_details: Dict[str, Any]) -> str:
        """Сообщение об ошибке валидации файла"""
        error_type = error_details.get("type", "unknown")
        
        if error_type == "size":
            actual_size = error_details.get("actual_size", 0)
            max_size = error_details.get("max_size", 20)
            actual_mb = actual_size / (1024 * 1024)
            
            return (
                f"📦 **Файл слишком большой**\n\n"
                f"Размер файла: {actual_mb:.1f} MB\n"
                f"Максимальный размер: {max_size} MB\n\n"
                f"💡 **Что можно сделать:**\n"
                f"• Сжать файл с помощью программ для конвертации\n"
                f"• Разделить запись на несколько частей\n"
                f"• Использовать формат с лучшим сжатием (MP3)\n"
                f"• Снизить качество аудио для уменьшения размера\n"
                f"• Система автоматически сжимает файлы для ускорения обработки"
            )
        
        elif error_type == "format":
            file_ext = error_details.get("extension", "")
            supported_formats = error_details.get("supported_formats", [])
            
            return (
                f"📁 **Неподдерживаемый формат файла**\n\n"
                f"Формат файла: {file_ext}\n\n"
                f"✅ **Поддерживаемые форматы:**\n"
                f"🎵 Аудио: {', '.join(supported_formats.get('audio', []))}\n"
                f"🎬 Видео: {', '.join(supported_formats.get('video', []))}\n\n"
                f"💡 **Что можно сделать:**\n"
                f"• Конвертировать файл в поддерживаемый формат\n"
                f"• Отправить файл как документ\n"
                f"• Использовать онлайн-конвертеры\n"
                f"• Система автоматически сжимает файлы для ускорения обработки"
            )
        
        return cls.error_message("validation", str(error_details))
    
    @classmethod
    def templates_help_message(cls) -> str:
        """Справка по работе с шаблонами"""
        return (
            "📝 **Управление шаблонами протоколов**\n\n"
            
            "🎨 **Что такое шаблоны?**\n"
            "Шаблоны определяют структуру и содержание итогового протокола. "
            "Вы можете использовать готовые шаблоны или создать собственные.\n\n"
            
            "✨ **Доступные переменные:**\n"
            "• `{{ participants }}` - список участников\n"
            "• `{{ agenda }}` - повестка дня\n"
            "• `{{ discussion }}` - основное обсуждение\n"
            "• `{{ decisions }}` - принятые решения\n"
            "• `{{ tasks }}` - задачи и ответственные\n"
            "• `{{ date }}` - дата встречи\n"
            "• `{{ time }}` - время встречи\n"
            "• `{{ speakers_summary }}` - анализ участников\n"
            "• `{{ speaker_contributions }}` - вклад каждого участника\n\n"
            
            "🔧 **Создание шаблона:**\n"
            "1. Нажмите \"➕ Добавить шаблон\"\n"
            "2. Введите название и описание\n"
            "3. Создайте содержимое с переменными\n"
            "4. Просмотрите результат\n"
            "5. Сохраните шаблон\n\n"
            
            "📋 **Пример простого шаблона:**\n"
            "```\n"
            "# Протокол встречи\n"
            "Дата: {{ date }}\n"
            "Участники: {{ participants }}\n\n"
            "## Обсуждение\n"
            "{{ discussion }}\n\n"
            "## Решения\n"
            "{{ decisions }}\n"
            "```\n\n"
            
            "💡 **Советы:**\n"
            "• Используйте Markdown для форматирования\n"
            "• Добавляйте эмодзи для наглядности\n"
            "• Тестируйте шаблоны с предпросмотром\n"
            "• Создавайте специализированные шаблоны для разных типов встреч"
        )
