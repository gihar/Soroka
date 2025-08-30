#!/usr/bin/env python3
"""
Тестовый скрипт для проверки логики сжатия
"""

import asyncio
import os
from pathlib import Path
from src.services.transcription_service import TranscriptionService
from src.ux.progress_tracker import ProgressTracker
from aiogram import Bot
from aiogram.types import Message

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

async def test_compression():
    """Тест логики сжатия"""
    print("🧪 Тестирование логики сжатия...")
    
    # Создаем мок-объекты
    bot = MockBot()
    message = MockMessage()
    
    # Создаем прогресс-трекер
    progress_tracker = ProgressTracker(bot, 123456, message)
    progress_tracker.setup_default_stages()
    
    # Создаем сервис транскрипции
    transcription_service = TranscriptionService()
    
    # Создаем тестовый аудиофайл (если есть)
    test_file = "temp/test_audio.mp3"
    if not os.path.exists(test_file):
        print(f"⚠️ Тестовый файл {test_file} не найден")
        print("Создаем заглушку для тестирования...")
        
        # Создаем заглушку
        os.makedirs("temp", exist_ok=True)
        with open(test_file, "wb") as f:
            f.write(b"fake audio data" * 1000)  # ~16KB файл
    
    print(f"📁 Тестируем файл: {test_file}")
    
    # Тестируем предобработку
    print("\n🔄 Тестирование предобработки файла...")
    processed_file, compression_info = transcription_service._preprocess_for_groq(test_file)
    
    print(f"📊 Результат предобработки:")
    print(f"   Обработанный файл: {processed_file}")
    print(f"   Информация о сжатии: {compression_info}")
    
    # Тестируем callback сжатия
    if compression_info and compression_info.get("compressed", False):
        print("\n🎯 Тестирование callback сжатия...")
        
        # Запускаем этап транскрипции
        await progress_tracker.start_stage("transcription")
        
        # Создаем callback
        def test_callback(percent, message, compression_info=None):
            print(f"📞 Callback вызван: {percent}% - {message}")
            if compression_info:
                print(f"   Информация о сжатии: {compression_info}")
            
            # Вызываем обновление прогресса
            asyncio.create_task(
                progress_tracker.update_stage_progress(
                    "transcription", percent, message, compression_info
                )
            )
        
        # Вызываем callback с информацией о сжатии
        test_callback(100, "compression_complete", compression_info)
        
        # Ждем немного для обработки
        await asyncio.sleep(1)
        
        # Завершаем этап
        await progress_tracker.complete_stage("transcription")
        
    else:
        print("⚠️ Файл не был сжат, пропускаем тест callback")
    
    print("\n✅ Тест завершен!")

if __name__ == "__main__":
    asyncio.run(test_compression())
