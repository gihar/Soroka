"""Снапшот content-строк 7 системных шаблонов на 2026-07-19 (ДО бриф-рефакторинга).

Заморожённая эталонная копия: сгенерирована программно с TemplateLibrary и
вставлена дословно. Тест бриф-компилятора требует строкового равенства
сгенерированного из брифа контента этим строкам (байт-в-байт).

НЕ РЕДАКТИРОВАТЬ вручную. При осознанном изменении шаблона — перегенерировать.
"""

SYSTEM_TEMPLATES_SNAPSHOT: dict[str, str] = {
    'Стандартный протокол встречи': (
        """# {{ meeting_title or 'Протокол встречи' }}

{% if date %}**Дата:** {{ date }}{% if time %} · {{ time }}{% endif %}
{% endif %}{% if participants %}**👥 Участники:**
{{ participants }}
{% endif %}
{% if agenda %}
## 📋 Повестка дня
{{ agenda }}
{% endif %}
{% if decisions %}
## ✅ Решения
{{ decisions }}
{% endif %}
{% if action_items %}
## 📌 Задачи и сроки
{{ action_items }}
{% endif %}
{% if risks_and_blockers %}
## ⚠️ Блокеры и риски
{{ risks_and_blockers }}
{% endif %}
{% if key_points %}
## 💡 Ключевые выводы
{{ key_points }}
{% endif %}
{% if discussion %}
## 💬 Обсуждение
{{ discussion }}
{% endif %}
{% if questions %}
## ❓ Открытые вопросы
{{ questions }}
{% endif %}
{% if next_steps %}
## 📅 Следующие шаги
{{ next_steps }}
{% endif %}"""
    ),
    'Краткое резюме встречи': (
        """# {{ meeting_title or 'Резюме встречи' }}

{% if date %}**Дата:** {{ date }}{% if time %} · {{ time }}{% endif %}
{% endif %}{% if participants %}**👥 Участники:**
{{ participants }}
{% endif %}
{% if decisions %}
## ✅ Решения
{{ decisions }}
{% endif %}
{% if action_items %}
## 📌 Задачи и сроки
{{ action_items }}
{% endif %}
{% if key_points %}
## 💡 Ключевые выводы
{{ key_points }}
{% endif %}
{% if next_steps %}
## 📅 Следующие шаги
{{ next_steps }}
{% endif %}"""
    ),
    'Техническое совещание': (
        """# {{ meeting_title or 'Техническое совещание' }}

{% if date %}**Дата:** {{ date }}{% if time %} · {{ time }}{% endif %}
{% endif %}{% if participants %}**👥 Участники:**
{{ participants }}
{% endif %}
{% if agenda %}
## 📋 Повестка дня
{{ agenda }}
{% endif %}
{% if decisions %}
## ✅ Решения
{{ decisions }}
{% endif %}
{% if action_items %}
## 📌 Задачи и сроки
{{ action_items }}
{% endif %}
{% if risks_and_blockers %}
## ⚠️ Блокеры и риски
{{ risks_and_blockers }}
{% endif %}
{% if technical_issues %}
## Технические вопросы
{{ technical_issues }}
{% endif %}
{% if architecture_decisions %}
## Архитектурные решения
{{ architecture_decisions }}
{% endif %}
{% if technical_tasks %}
## Технические задачи
{{ technical_tasks }}
{% endif %}
{% if discussion %}
## 💬 Обсуждение
{{ discussion }}
{% endif %}
{% if next_sprint_plans %}
## 📅 Планы на следующий спринт
{{ next_sprint_plans }}
{% endif %}"""
    ),
    'Протокол ОД (Поручения)': (
        """# {{ meeting_title or 'Протокол поручений' }}

{% if date %}**Дата:** {{ date }}{% if time %} · {{ time }}{% endif %}
{% endif %}{% if participants %}**👥 Участники:**
{{ participants }}
{% endif %}
{% if tasks_od %}
## 📌 Поручения
{{ tasks_od }}
{% else %}
Поручений в записи не зафиксировано.
{% endif %}
{% if additional_notes %}
## Дополнительные заметки
{{ additional_notes }}
{% endif %}"""
    ),
    'Дейли': (
        """# {{ meeting_title or 'Дейли' }}

{% if date %}**Дата:** {{ date }}{% if time %} · {{ time }}{% endif %}
{% endif %}{% if participants %}**👥 Участники:**
{{ participants }}
{% endif %}
{% if decisions %}
## ✅ Решения
{{ decisions }}
{% endif %}
{% if action_items %}
## 📌 Задачи и сроки
{{ action_items }}
{% endif %}
{% if risks_and_blockers %}
## ⚠️ Блокеры и риски
{{ risks_and_blockers }}
{% endif %}
{% if yesterday_progress %}
## Вчера
{{ yesterday_progress }}
{% endif %}
{% if today_plans %}
## Сегодня
{{ today_plans }}
{% endif %}
{% if discussion %}
## 💬 Обсуждение
{{ discussion }}
{% endif %}
{% if next_steps %}
## 📅 Следующие шаги
{{ next_steps }}
{% endif %}"""
    ),
    'Ретроспектива спринта': (
        """# {{ meeting_title or 'Ретроспектива спринта' }}

{% if date %}**Дата:** {{ date }}{% if time %} · {{ time }}{% endif %}
{% endif %}{% if participants %}**👥 Участники:**
{{ participants }}
{% endif %}
{% if decisions %}
## ✅ Решения
{{ decisions }}
{% endif %}
{% if action_items %}
## 📌 Задачи и сроки
{{ action_items }}
{% endif %}
{% if risks_and_blockers %}
## ⚠️ Блокеры и риски
{{ risks_and_blockers }}
{% endif %}
{% if went_well %}
## Что прошло хорошо
{{ went_well }}
{% endif %}
{% if to_improve %}
## Что улучшить
{{ to_improve }}
{% endif %}
{% if dialogue_analysis %}
## Анализ взаимодействия
{{ dialogue_analysis }}
{% endif %}
{% if discussion %}
## 💬 Обсуждение
{{ discussion }}
{% endif %}
{% if next_sprint_plans %}
## 📅 Следующий спринт
{{ next_sprint_plans }}
{% endif %}"""
    ),
    'Лекция и презентация': (
        """# {{ meeting_title or 'Лекция' }}

{% if date %}**Дата:** {{ date }}{% if time %} · {{ time }}{% endif %}
{% endif %}{% if lecturer %}**Лектор:** {{ lecturer }}
{% endif %}{% if participants %}**👥 Участники:**
{{ participants }}
{% endif %}
{% if learning_objectives %}
## Цели обучения
{{ learning_objectives }}
{% endif %}
{% if agenda %}
## 📋 Структура лекции
{{ agenda }}
{% endif %}
{% if key_concepts %}
## Ключевые концепции
{{ key_concepts }}
{% endif %}
{% if discussion %}
## 💬 Основной материал
{{ discussion }}
{% endif %}
{% if examples_and_cases %}
## Примеры и кейсы
{{ examples_and_cases }}
{% endif %}
{% if questions_and_answers %}
## ❓ Вопросы и ответы
{{ questions_and_answers }}
{% endif %}
{% if key_points %}
## 💡 Ключевые выводы
{{ key_points }}
{% endif %}
{% if homework %}
## Домашнее задание
{{ homework }}
{% endif %}
{% if additional_materials %}
## Дополнительные материалы
{{ additional_materials }}
{% endif %}
{% if next_steps %}
## 📅 Следующие шаги
{{ next_steps }}
{% endif %}"""
    ),
}
