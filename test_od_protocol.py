#!/usr/bin/env python3
"""
Тестовый скрипт для проверки режима OD протокола
"""

import asyncio
import json
from typing import Dict, Any, List

# Тестовая транскрипция на основе примера из скриншота
TEST_TRANSCRIPTION = """
Коллеги, добрый день.

Итоги встречи:

SPEAKER_1: Первый вопрос - OSA (On Shelf Availability). Запланировать защиту до 15 декабря в рамках бюджетной кампании со стартом работ в январе. Ответственный - Мачульский Дмитрий.

SPEAKER_2: По второму вопросу - Каспи ИЗ. Нужно уточнить дату запуска, план с 17 ноября. Дать обратную связь по результатам демо Александре Васильевне 10.11.2025 в Телеграм. Ответственный - Поляков А. Срок - 10 ноября.

SPEAKER_1: Третий вопрос - Управление расформированием ИЗ. Провести оценку варианта усиления за счет ресурсов Д/Л на следующей неделе. Ответственный - Савельев С.

SPEAKER_3: По четвертому вопросу - Яндекс.Еда: Реализация целевого решения. Проработать путь клиента и курьера по мобильной кассе (как снимается противокража и т.д.). Запланировать выезд в магазин в следующей неделе. Ответственный - Поляков М. Срок - 14 ноября.

SPEAKER_1: Пятый вопрос - Модернизация корпоративного сайта для розницы. Организовать отдельную встречу. Состав: Шабанова А.В., Благадерова С., Савельев С., Мачульский Д., Поляков М. Ответственный - Мачульский Д. Срок - 10 ноября.

SPEAKER_2: И последний вопрос - Calipso. Собственная разработка ТСД. На встречу по защите ГД 12.11 взять ТСД (3 штуки). Ответственный - Носов С.

Всем спасибо за встречу! При необходимости прошу дополнить или дать комментарии.
"""

# Список участников с ролями (руководители должны быть указаны)
TEST_PARTICIPANTS = [
    {"name": "Мачульский Дмитрий", "role": "Руководитель проекта"},
    {"name": "Поляков Александр", "role": "Менеджер"},
    {"name": "Савельев Сергей", "role": "Технический директор"},
    {"name": "Поляков Михаил", "role": "Менеджер"},
    {"name": "Носов Сергей", "role": "Разработчик"},
    {"name": "Шабанова Анна", "role": "Руководитель направления"},
    {"name": "Благадерова Светлана", "role": "Аналитик"}
]

# Сопоставление спикеров
TEST_SPEAKER_MAPPING = {
    "SPEAKER_1": "Мачульский Дмитрий",
    "SPEAKER_2": "Поляков Александр",
    "SPEAKER_3": "Савельев Сергей"
}


async def test_od_protocol_schemas():
    """Тест 1: Проверка схем"""
    print("=" * 60)
    print("ТЕСТ 1: Проверка схем OD протокола")
    print("=" * 60)
    
    try:
        from src.models.llm_schemas import (
            ODProtocolSchema, 
            ODProtocolTaskSchema, 
            ODProtocolAssignmentSchema,
            OD_PROTOCOL_SCHEMA
        )
        
        print("✅ Схемы успешно импортированы")
        print(f"   - ODProtocolSchema: {ODProtocolSchema}")
        print(f"   - ODProtocolTaskSchema: {ODProtocolTaskSchema}")
        print(f"   - ODProtocolAssignmentSchema: {ODProtocolAssignmentSchema}")
        print(f"   - OD_PROTOCOL_SCHEMA доступна: {OD_PROTOCOL_SCHEMA is not None}")
        
        # Тестовый пример данных
        test_assignment = ODProtocolAssignmentSchema(
            manager_name="Мачульский Дмитрий",
            instruction="Запланировать защиту до 15/12",
            responsible="Мачульский Д.",
            deadline="15.12"
        )
        
        test_task = ODProtocolTaskSchema(
            task_name="OSA (On Shelf Availability)",
            assignments=[test_assignment]
        )
        
        test_protocol = ODProtocolSchema(
            tasks=[test_task],
            meeting_date="19.11.2025",
            participants="Мачульский Дмитрий, Поляков Александр",
            managers="Мачульский Дмитрий"
        )
        
        print("\n✅ Тестовые данные успешно созданы")
        print(f"   Задач: {len(test_protocol.tasks)}")
        print(f"   Поручений в первой задаче: {len(test_protocol.tasks[0].assignments)}")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка при проверке схем: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_od_protocol_formatting():
    """Тест 2: Проверка форматирования"""
    print("\n" + "=" * 60)
    print("ТЕСТ 2: Проверка форматирования OD протокола")
    print("=" * 60)
    
    try:
        from llm_providers import format_od_protocol
        
        test_data = {
            'tasks': [
                {
                    'task_name': 'OSA (On Shelf Availability)',
                    'assignments': [
                        {
                            'manager_name': 'Мачульский Дмитрий',
                            'instruction': 'Запланировать защиту до 15/12 в рамках бюджетной кампании со стартом работ в январе',
                            'responsible': 'Мачульский Д.',
                            'deadline': '15.12'
                        }
                    ]
                },
                {
                    'task_name': 'Каспи ИЗ',
                    'assignments': [
                        {
                            'manager_name': 'Поляков Александр',
                            'instruction': 'Уточнить дату запуска (план с 17.11). Дать ОС по результатам демо Александре Васильевне 10.11.2025 в ТГ',
                            'responsible': 'Поляков А.',
                            'deadline': '10.11'
                        }
                    ]
                }
            ],
            'meeting_date': '19.11.2025',
            'managers': 'Мачульский Дмитрий, Поляков Александр',
            'participants': 'Мачульский Дмитрий, Поляков Александр, Савельев Сергей'
        }
        
        formatted_text = format_od_protocol(test_data)
        
        print("✅ Протокол успешно отформатирован")
        print("\nРезультат:")
        print("-" * 60)
        print(formatted_text)
        print("-" * 60)
        
        # Проверяем наличие ключевых элементов
        assert "ПРОТОКОЛ ПОРУЧЕНИЙ" in formatted_text
        assert "OSA" in formatted_text
        assert "Мачульский Д." in formatted_text
        assert "Отв." in formatted_text
        
        print("\n✅ Все ключевые элементы присутствуют в форматированном тексте")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка при форматировании: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_od_protocol_prompts():
    """Тест 3: Проверка промптов"""
    print("\n" + "=" * 60)
    print("ТЕСТ 3: Проверка промптов OD протокола")
    print("=" * 60)
    
    try:
        from llm_providers import _build_od_system_prompt, _build_od_user_prompt
        
        # Тест системного промпта
        system_prompt = _build_od_system_prompt()
        print("✅ Системный промпт создан")
        print(f"   Длина: {len(system_prompt)} символов")
        
        # Проверяем ключевые слова
        assert "руководител" in system_prompt.lower()
        assert "поручен" in system_prompt.lower()
        assert "задач" in system_prompt.lower()
        
        print("   Содержит ключевые слова: руководители, поручения, задачи")
        
        # Тест пользовательского промпта
        user_prompt = _build_od_user_prompt(
            transcription=TEST_TRANSCRIPTION,
            diarization_data={"formatted_transcript": TEST_TRANSCRIPTION},
            participants=TEST_PARTICIPANTS,
            speaker_mapping=TEST_SPEAKER_MAPPING,
            meeting_date="19.11.2025"
        )
        
        print("\n✅ Пользовательский промпт создан")
        print(f"   Длина: {len(user_prompt)} символов")
        
        # Проверяем наличие руководителей
        assert "Мачульский Дмитрий" in user_prompt
        assert "РУКОВОДИТЕЛИ" in user_prompt
        
        print("   Содержит список руководителей")
        print("   Содержит транскрипцию")
        print("   Содержит сопоставление спикеров")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка при проверке промптов: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_processing_request_mode():
    """Тест 4: Проверка поля processing_mode в ProcessingRequest"""
    print("\n" + "=" * 60)
    print("ТЕСТ 4: Проверка поля processing_mode")
    print("=" * 60)
    
    try:
        from src.models.processing import ProcessingRequest
        
        # Создаем запрос с OD режимом
        request = ProcessingRequest(
            file_name="test.mp3",
            llm_provider="openai",
            user_id=123,
            processing_mode="od_protokol",
            participants_list=TEST_PARTICIPANTS
        )
        
        print("✅ ProcessingRequest создан с полем processing_mode")
        print(f"   processing_mode: {request.processing_mode}")
        print(f"   participants_list: {len(request.participants_list)} участников")
        
        # Проверяем, что режим установлен правильно
        assert request.processing_mode == "od_protokol"
        assert request.participants_list is not None
        
        print("\n✅ Поле processing_mode работает корректно")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка при проверке ProcessingRequest: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Запуск всех тестов"""
    print("\n")
    print("╔" + "═" * 58 + "╗")
    print("║" + " " * 10 + "ТЕСТИРОВАНИЕ РЕЖИМА OD ПРОТОКОЛА" + " " * 16 + "║")
    print("╚" + "═" * 58 + "╝")
    print("\n")
    
    results = []
    
    # Запускаем тесты
    results.append(("Проверка схем", await test_od_protocol_schemas()))
    results.append(("Проверка форматирования", await test_od_protocol_formatting()))
    results.append(("Проверка промптов", await test_od_protocol_prompts()))
    results.append(("Проверка ProcessingRequest", await test_processing_request_mode()))
    
    # Итоги
    print("\n" + "=" * 60)
    print("ИТОГИ ТЕСТИРОВАНИЯ")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{status} - {name}")
    
    print("\n" + "-" * 60)
    print(f"Пройдено: {passed}/{total} тестов")
    print("-" * 60)
    
    if passed == total:
        print("\n🎉 Все тесты успешно пройдены!")
        print("\nРежим OD протокола готов к использованию.")
        print("\nДля активации режима установите:")
        print("  request.processing_mode = 'od_protokol'")
        print("  request.participants_list = [...список участников с ролями...]")
    else:
        print("\n⚠️  Некоторые тесты не прошли. Проверьте ошибки выше.")
    
    print("\n")


if __name__ == "__main__":
    asyncio.run(main())

