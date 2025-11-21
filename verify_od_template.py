#!/usr/bin/env python3
"""
Проверка шаблонов OD протокола и образовательных шаблонов
"""

import sys
import os
import re
from jinja2 import Template

# Добавляем путь к проекту
sys.path.append('.')
from src.services.template_library import TemplateLibrary

def verify_od_template():
    """Проверка OD шаблона"""
    file_path = os.path.join(os.getcwd(), "src/services/template_library.py")

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        print(f"ERROR: File not found: {file_path}")
        return False

    print("🔍 Проверка OD протокола")
    print("=" * 40)

    # Extract od_protocol content using regex
    match = re.search(r'"id":\s*"od_protocol".*?"content":\s*"""(.*?)"""', content, re.DOTALL)

    if not match:
        print("ERROR: 'od_protocol' template content not found in file via regex!")
        # Debug: print a snippet where it should be
        start_idx = content.find('"id": "od_protocol"')
        if start_idx != -1:
            print(f"Found 'id': 'od_protocol' at index {start_idx}. Context:")
            print(content[start_idx:start_idx+500])
        return False

    template_content = match.group(1)
    print("✅ OD шаблон найден")

    # Sample data matching ODProtocolSchema structure
    data = {
        "meeting_date": "20 октября 2024",
        "managers": "Иван Иванов, Петр Петров",
        "participants": "Алексей Сидоров, Мария Кузнецова",
        "tasks": [
            {
                "task_name": "Разработка нового функционала",
                "assignments": [
                    {
                        "instruction": "Подготовить архитектуру",
                        "manager_name": "Иван Иванов",
                        "responsible": "Алексей Сидоров",
                        "deadline": "25.10.2024"
                    },
                    {
                        "instruction": "Согласовать требования",
                        "manager_name": "Петр Петров",
                        "responsible": "Мария Кузнецова",
                        "deadline": ""
                    }
                ]
            }
        ],
        "additional_notes": "Важно соблюдать сроки."
    }

    print("\nОтрисовка шаблона с тестовыми данными...\n")

    try:
        template = Template(template_content)
        rendered = template.render(**data)
        print("-" * 40)
        print(rendered)
        print("-" * 40)
        print("✅ OD шаблон работает корректно")
        return True
    except Exception as e:
        print(f"\n❌ Ошибка отрисовки OD шаблона: {e}")
        return False

def verify_educational_integration():
    """Проверка интеграции образовательных шаблонов"""
    print("\n🎓 Проверка образовательных шаблонов")
    print("=" * 40)

    try:
        library = TemplateLibrary()

        # Проверка категорий
        print("📋 Категории в системе:")
        for cat_id, description in library.CATEGORIES.items():
            print(f"  - {cat_id}: {description}")

        # Проверка образовательных шаблонов
        educational_templates = library.get_educational_templates()
        print(f"\n✅ Найдено образовательных шаблонов: {len(educational_templates)}")

        if len(educational_templates) == 0:
            print("❌ Образовательные шаблоны не найдены")
            return False

        for template in educational_templates:
            print(f"  - {template['name']} (ID: {template.get('id', 'N/A')})")

        # Проверка общего количества
        all_templates = library.get_all_templates()
        print(f"\n📊 Всего шаблонов в системе: {len(all_templates)}")

        # Тестирование рендеринга образовательного шаблона
        edu_template = educational_templates[0]
        print(f"\n🧪 Тестирование шаблона: {edu_template['name']}")

        test_data = {
            "date": "20 ноября 2024",
            "time": "14:30",
            "participants": "Профессор Иванов",
            "learning_objectives": "Изучить основы программирования на Python",
            "key_concepts": "Переменные, функции, классы",
            "practical_exercises": "Написать простую программу",
            "materials": "Учебник по Python, ноутбук с IDE"
        }

        try:
            template = Template(edu_template['content'])
            rendered = template.render(**test_data)
            print("✅ Образовательный шаблон работает корректно")
            return True
        except Exception as e:
            print(f"❌ Ошибка рендеринга образовательного шаблона: {e}")
            return False

    except Exception as e:
        print(f"❌ Ошибка проверки образовательных шаблонов: {e}")
        return False

if __name__ == "__main__":
    od_ok = verify_od_template()
    edu_ok = verify_educational_integration()

    print(f"\n🎯 Результаты проверки:")
    print(f"   OD шаблон: {'✅' if od_ok else '❌'}")
    print(f"   Образовательные шаблоны: {'✅' if edu_ok else '❌'}")

    if od_ok and edu_ok:
        print("\n🎉 Все проверки пройдены успешно!")
    else:
        print("\n⚠️ Обнаружены проблемы, требующие внимания")
