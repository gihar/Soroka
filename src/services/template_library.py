"""
Библиотека профессиональных шаблонов для встреч
"""

from typing import List, Dict, Any


class TemplateLibrary:
    """Профессиональная библиотека шаблонов"""

    def get_all_templates(self) -> List[Dict[str, Any]]:
        """Все шаблоны библиотеки"""
        return [
            {
                "id": "od_protocol",
                "name": "Протокол поручений руководителей",
                "description": "Специальный формат для протокола поручений руководителей (OD)",
                "tags": ["поручения", "од", "руководители", "протокол"],
                "keywords": ["од", "поручение", "задача", "срок", "ответственный"],
                "is_default": False,
                "content": """ПРОТОКОЛ ПОРУЧЕНИЙ
============================================================
{% if meeting_date %}Дата встречи: {{ meeting_date }}
{% endif %}
{% if participants %}Участники: {{ participants }}
{% endif %}
============================================================

{% if tasks_od %}
{{ tasks_od }}
{% else %}
   (Поручений не зафиксировано)

{% endif %}
{% if additional_notes %}
============================================================
ДОПОЛНИТЕЛЬНЫЕ ЗАМЕТКИ:
{{ additional_notes }}
{% endif %}"""
            },
            {
                "name": "Daily Standup",
                "description": "Ежедневные standup встречи команды",
                "tags": ["daily", "standup", "scrum"],
                "keywords": ["standup", "вчера", "сегодня", "блокеры", "ежедневно"],
                "is_default": True,
                "content": """# Daily Standup

**Дата:** {{ date }}
**Команда:** {{ participants }}

{% if speaker_contributions %}
## Статус по участникам
{{ speaker_contributions }}
{% endif %}

## Что сделано вчера
{{ discussion }}

## Планы на сегодня
{{ action_items }}

## Блокеры и проблемы
{{ risks_and_blockers }}

## Быстрые решения
{{ decisions }}

## Следующий standup
{{ next_steps }}"""
            },
            {
                "name": "Sprint Retrospective",
                "description": "Ретроспектива спринта для улучшения процессов",
                "tags": ["retrospective", "agile", "improvement"],
                "keywords": ["ретроспектива", "что хорошо", "что улучшить", "действия", "retro"],
                "is_default": True,
                "content": """# Sprint Retrospective

**Дата:** {{ date }}
**Команда:** {{ participants }}

## Что прошло хорошо ✅
{{ key_points }}

## Что можно улучшить 🔄
{{ discussion }}

{% if dialogue_analysis %}
## Анализ взаимодействия
{{ dialogue_analysis }}
{% endif %}

## Выявленные проблемы
{{ risks_and_blockers }}

## Решения и улучшения
{{ decisions }}

## Action Items
{{ action_items }}

## Эксперименты на следующий спринт
{{ next_sprint_plans }}

---
*Retro generated automatically*"""
            },
            {
                "id": "education_lecture",
                "name": "Лекция и презентация",
                "description": "Шаблон для лекций и презентаций с фокусом на структуре материала",
                "tags": ["лекция", "презентация", "теория", "концепции"],
                "keywords": ["лекция", "презентация", "теория", "концепции", "определения", "примеры", "материал"],
                "is_default": True,
                "content": """# Лекция/Презентация

**Дата:** {{ date }}
**Время:** {{ time }}
**Лектор/Преподаватель:** {{ participants }}
**Тема:** {{ learning_objectives }}

{% if speakers_summary %}
## Информация о лекторе
{{ speakers_summary }}
{% endif %}

## Цели обучения
{{ learning_objectives }}

## Структура лекции
{{ agenda }}

## Основное содержание

### {% if key_concepts %}Ключевые концепции и определения{% endif %}
{{ key_concepts }}

### {% if discussion %}Основной материал{% endif %}
{{ discussion }}

{% if examples_and_cases %}
## Примеры и кейсы
{{ examples_and_cases }}
{% endif %}

{% if practical_demonstration %}
## Практическая демонстрация
{{ practical_demonstration }}
{% endif %}

{% if questions_and_answers %}
## Вопросы и ответы
{{ questions_and_answers }}
{% endif %}

## Ключевые выводы
{{ key_points }}

{% if homework %}
## Домашнее задание
{{ homework }}
{% endif %}

{% if additional_materials %}
## Дополнительные материалы
{{ additional_materials }}
{% endif %}

## Следующая лекция/тема
{{ next_steps }}

---
*Протокол лекции создан автоматически с сохранением образовательной структуры*"""
            },
        ]
