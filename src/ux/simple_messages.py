"""
Упрощенные сообщения для пользователя
"""

from typing import Dict, Any


class SimpleMessages:
    """Упрощенные сообщения для лучшего UX"""
    
    @staticmethod
    def processing_start() -> str:
        """Начало обработки"""
        return (
            "🔄 **Обработка файла началась**\n\n"
            "⏳ Подготавливаю файл к обработке..."
        )
    
    @staticmethod
    def processing_complete(duration: float) -> str:
        """Завершение обработки"""
        return (
            "✅ **Обработка завершена!**\n\n"
            f"⏱️ Время: {duration:.0f}с\n"
            "📄 Протокол готов и будет отправлен ниже."
        )
    
    @staticmethod
    def compression_optimized(original_mb: float, compressed_mb: float, ratio: float) -> str:
        """Информация об оптимизации файла"""
        return (
            f"🗜️ **Файл оптимизирован!**\n\n"
            f"📊 Размер уменьшен на {ratio:.0f}%\n"
            f"({original_mb:.1f}MB → {compressed_mb:.1f}MB)\n\n"
            f"🔄 Продолжаю обработку..."
        )
    
    @staticmethod
    def error_generic(stage_name: str, error_message: str) -> str:
        """Общая ошибка"""
        return (
            f"❌ **Ошибка при обработке**\n\n"
            f"Этап: {stage_name}\n"
            f"Ошибка: {error_message}\n\n"
            f"Попробуйте загрузить файл еще раз."
        )
    
    @staticmethod
    def error_file_too_large() -> str:
        """Ошибка - файл слишком большой"""
        return (
            "📦 **Файл слишком большой**\n\n"
            "Система автоматически попытается сжать файл, "
            "но произошла ошибка. Попробуйте:\n\n"
            "• Сжать аудиофайл до меньшего размера\n"
            "• Разделить длинную запись на несколько частей\n"
            "• Использовать формат с лучшим сжатием (MP3)"
        )
    
    @staticmethod
    def error_transcription() -> str:
        """Ошибка транскрипции"""
        return (
            "🎤 **Ошибка при транскрипции**\n\n"
            "Не удалось преобразовать аудио в текст. Попробуйте:\n\n"
            "• Проверить качество аудио\n"
            "• Убедиться, что речь четкая и без шумов\n"
            "• Использовать файл меньшего размера"
        )
    
    @staticmethod
    def error_message_too_long() -> str:
        """Ошибка - сообщение слишком длинное"""
        return (
            "📄 **Результат слишком длинный**\n\n"
            "Протокол превышает лимит Telegram. Попробуйте:\n\n"
            "• Обработать файл меньшего размера\n"
            "• Разделить длинную запись на части\n"
            "• Использовать более короткий аудиофайл"
        )
    
    @staticmethod
    def stage_preparation() -> str:
        """Этап подготовки"""
        return "📁 Подготавливаю файл к обработке..."
    
    @staticmethod
    def stage_transcription() -> str:
        """Этап транскрипции"""
        return "🎯 Преобразую аудио в текст..."
    
    @staticmethod
    def stage_analysis() -> str:
        """Этап анализа"""
        return "🤖 Анализирую содержание и создаю протокол..."
    
    @staticmethod
    def progress_bar() -> str:
        """Упрощенный прогресс-бар"""
        return "▰▰▰▰▰▰▰▰▰▰"
    
    @staticmethod
    def format_progress_text(stages: Dict[str, Any], current_stage: str = None, 
                           total_elapsed: float = 0) -> str:
        """Форматировать текст прогресса"""
        text = "🔄 **Обработка файла**\n\n"
        
        for stage_id, stage in stages.items():
            if stage.is_completed:
                text += f"✅ {stage.emoji} {stage.name}\n"
            elif stage.is_active:
                progress_bar = SimpleMessages.progress_bar()
                text += f"🔄 {stage.emoji} {stage.name} {progress_bar}\n"
                text += f"   _{stage.description}_\n"
            else:
                text += f"⏳ {stage.emoji} {stage.name}\n"
        
        # Показываем время только если прошло больше 10 секунд
        if total_elapsed > 10:
            text += f"\n⏱️ {total_elapsed:.0f}с"
        
        return text
