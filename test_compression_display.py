#!/usr/bin/env python3
"""
Простой тест отображения информации о сжатии
"""

import asyncio
from src.ux.progress_tracker import ProgressTracker

class MockBot:
    async def send_message(self, chat_id, text, parse_mode=None):
        print(f"📱 Сообщение в чат {chat_id}:")
        print(text)
        print("-" * 50)
        return MockMessage()

class MockMessage:
    async def edit_text(self, text, parse_mode=None):
        print(f"✏️ Обновление сообщения:")
        print(text)
        print("-" * 50)

async def test_compression_display():
    """Тест отображения информации о сжатии"""
    print("🧪 Тестирование отображения информации о сжатии...")
    
    # Создаем мок-объекты
    bot = MockBot()
    message = MockMessage()
    
    # Создаем прогресс-трекер
    progress_tracker = ProgressTracker(bot, 123456, message)
    progress_tracker.setup_default_stages()
    
    # Запускаем этап транскрипции
    await progress_tracker.start_stage("transcription")
    
    # Создаем тестовую информацию о сжатии
    compression_info = {
        "compressed": True,
        "original_size_mb": 25.5,
        "compressed_size_mb": 18.2,
        "compression_ratio": 28.6,
        "compression_saved_mb": 7.3
    }
    
    print(f"📊 Тестовая информация о сжатии: {compression_info}")
    
    # Вызываем отображение информации о сжатии
    await progress_tracker._show_compression_info(compression_info)
    
    print("✅ Тест завершен!")

if __name__ == "__main__":
    asyncio.run(test_compression_display())
