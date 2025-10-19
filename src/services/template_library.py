"""
Библиотека профессиональных шаблонов для встреч
"""

from typing import List, Dict, Any


class TemplateLibrary:
    """Профессиональная библиотека шаблонов"""
    
    CATEGORIES = {
        "management": "Управленческие встречи",
        "product": "Продуктовые встречи",
        "technical": "Технические встречи",
        "sales": "Продажи"
    }
    
    def get_management_templates(self) -> List[Dict[str, Any]]:
        """6 управленческих шаблонов"""
        return [
            {
                "name": "Стратегическая сессия руководства",
                "description": "Шаблон для стратегических встреч с фокусом на целях и планах",
                "category": "management",
                "tags": ["strategy", "leadership", "planning"],
                "keywords": ["стратегия", "цели", "квартал", "бюджет", "KPI", "планы", "направления"],
                "is_default": True,
                "content": """# Стратегическая сессия

## Основная информация
**Дата:** {{ date }}
**Время:** {{ time }}
**Участники:** {{ participants }}

{% if speakers_summary %}
## Анализ участников
{{ speakers_summary }}
{% endif %}

## Стратегические цели
{{ agenda }}

## Ключевые обсуждения
{{ discussion }}

{% if speaker_contributions %}
## Вклад руководителей
{{ speaker_contributions }}
{% endif %}

## Принятые стратегические решения
{{ decisions }}

## KPI и метрики успеха
{{ key_points }}

## План действий и ответственные
{{ tasks }}

## Следующие шаги
{{ next_steps }}

---
*Протокол стратегической сессии создан автоматически*"""
            },
            {
                "name": "Оперативное совещание руководителей",
                "description": "Ежедневные/еженедельные оперативные совещания",
                "category": "management",
                "tags": ["operations", "status", "daily"],
                "keywords": ["статус", "проблемы", "отчет", "прогресс", "задачи", "ситуация"],
                "is_default": True,
                "content": """# Оперативное совещание

**Дата:** {{ date }}
**Участники:** {{ participants }}

## Статус по направлениям
{{ discussion }}

{% if speaker_contributions %}
## Отчеты руководителей
{{ speaker_contributions }}
{% endif %}

## Выявленные проблемы и риски
{{ risks_and_blockers }}

## Оперативные решения
{{ decisions }}

## Задачи на период
{{ action_items }}

## Следующее совещание
{{ next_steps }}"""
            },
            {
                "name": "Бюджетное планирование",
                "description": "Встречи по планированию и контролю бюджета",
                "category": "management",
                "tags": ["budget", "finance", "planning"],
                "keywords": ["бюджет", "расходы", "инвестиции", "ROI", "финансы", "затраты"],
                "is_default": True,
                "content": """# Бюджетное планирование

**Дата:** {{ date }}
**Участники:** {{ participants }}

## Повестка
{{ agenda }}

## Текущая ситуация
{{ discussion }}

## Бюджетные решения
{{ decisions }}

## Распределение бюджета
{{ tasks }}

## План затрат
{{ action_items }}

## Контрольные точки
{{ next_steps }}"""
            },
            {
                "name": "Встреча по целям и OKR",
                "description": "Постановка и review целей, OKR сессии",
                "category": "management",
                "tags": ["okr", "goals", "objectives"],
                "keywords": ["OKR", "цели", "ключевые результаты", "метрики", "objectives"],
                "is_default": True,
                "content": """# Встреча по OKR

**Период:** {{ date }}
**Участники:** {{ participants }}

{% if speakers_summary %}
## Участники сессии
{{ speakers_summary }}
{% endif %}

## Цели (Objectives)
{{ agenda }}

## Обсуждение
{{ discussion }}

## Ключевые результаты (Key Results)
{{ key_points }}

## Утвержденные OKR
{{ decisions }}

## Ответственные и сроки
{{ tasks }}

## Метрики отслеживания
{{ action_items }}

## Следующая проверка
{{ next_steps }}"""
            },
            {
                "name": "Планирование ресурсов",
                "description": "Встречи по распределению команды и ресурсов",
                "category": "management",
                "tags": ["resources", "allocation", "team"],
                "keywords": ["ресурсы", "команда", "найм", "распределение", "загрузка", "capacity"],
                "is_default": True,
                "content": """# Планирование ресурсов

**Дата:** {{ date }}
**Участники:** {{ participants }}

## Текущая ситуация с ресурсами
{{ discussion }}

## Потребности в ресурсах
{{ agenda }}

## Решения по распределению
{{ decisions }}

## План найма и развития
{{ tasks }}

## Действия по оптимизации
{{ action_items }}

## Следующие шаги
{{ next_steps }}"""
            },
            {
                "name": "Анализ рисков и возможностей",
                "description": "Сессии по выявлению рисков и возможностей",
                "category": "management",
                "tags": ["risks", "opportunities", "swot"],
                "keywords": ["риски", "угрозы", "возможности", "SWOT", "анализ", "митигация"],
                "is_default": True,
                "content": """# Анализ рисков и возможностей

**Дата:** {{ date }}
**Участники:** {{ participants }}

## Выявленные риски
{{ risks_and_blockers }}

## Обсуждение
{{ discussion }}

## Возможности для роста
{{ key_points }}

## Решения по митигации рисков
{{ decisions }}

## План использования возможностей
{{ action_items }}

## Действия и ответственные
{{ tasks }}

## Следующие шаги
{{ next_steps }}"""
            }
        ]
    
    def get_product_templates(self) -> List[Dict[str, Any]]:
        """6 продуктовых шаблонов"""
        return [
            {
                "name": "Sprint Planning",
                "description": "Планирование спринта в Agile/Scrum",
                "category": "product",
                "tags": ["sprint", "planning", "agile", "scrum"],
                "keywords": ["спринт", "задачи", "story points", "capacity", "backlog", "планирование"],
                "is_default": True,
                "content": """# Sprint Planning

**Дата:** {{ date }}
**Команда:** {{ participants }}

{% if speakers_summary %}
## Состав команды
{{ speakers_summary }}
{% endif %}

## Цели спринта
{{ agenda }}

## Обзор backlog
{{ discussion }}

{% if speaker_contributions %}
## Вклад участников
{{ speaker_contributions }}
{% endif %}

## Выбранные задачи
{{ decisions }}

## Sprint Backlog
{{ tasks }}

## Story Points и capacity
{{ key_points }}

## Технические вопросы
{{ technical_issues }}

## Definition of Done
{{ action_items }}

## Следующие шаги
{{ next_steps }}

---
*Sprint Planning Protocol*"""
            },
            {
                "name": "Sprint Retrospective",
                "description": "Ретроспектива спринта для улучшения процессов",
                "category": "product",
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
                "name": "Product Roadmap Review",
                "description": "Обзор и обновление product roadmap",
                "category": "product",
                "tags": ["roadmap", "planning", "strategy"],
                "keywords": ["roadmap", "план", "фичи", "релизы", "приоритеты", "продукт"],
                "is_default": True,
                "content": """# Product Roadmap Review

**Дата:** {{ date }}
**Участники:** {{ participants }}

## Текущее состояние продукта
{{ discussion }}

## Приоритеты и фичи
{{ agenda }}

## Решения по roadmap
{{ decisions }}

## План релизов
{{ tasks }}

## Технические требования
{{ technical_tasks }}

## Ключевые метрики
{{ key_points }}

## Action Items
{{ action_items }}

## Следующий review
{{ next_steps }}"""
            },
            {
                "name": "Daily Standup",
                "description": "Ежедневные standup встречи команды",
                "category": "product",
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
                "name": "Product Discovery Session",
                "description": "Сессия исследования и discovery новых фич",
                "category": "product",
                "tags": ["discovery", "research", "user"],
                "keywords": ["исследование", "пользователи", "проблемы", "решения", "discovery", "user research"],
                "is_default": True,
                "content": """# Product Discovery Session

**Дата:** {{ date }}
**Участники:** {{ participants }}

## Исследуемая область
{{ agenda }}

## Проблемы пользователей
{{ discussion }}

## Идеи решений
{{ key_points }}

{% if dialogue_analysis %}
## Обсуждение команды
{{ dialogue_analysis }}
{% endif %}

## Гипотезы
{{ decisions }}

## План исследования
{{ tasks }}

## Следующие шаги
{{ action_items }}

## Метрики успеха
{{ next_steps }}"""
            },
            {
                "name": "Backlog Refinement",
                "description": "Grooming и уточнение backlog",
                "category": "product",
                "tags": ["backlog", "grooming", "estimation"],
                "keywords": ["backlog", "задачи", "оценка", "уточнение", "user story", "grooming"],
                "is_default": True,
                "content": """# Backlog Refinement

**Дата:** {{ date }}
**Команда:** {{ participants }}

## Рассмотренные истории
{{ agenda }}

## Обсуждение
{{ discussion }}

## Уточненные требования
{{ key_points }}

## Оценки (Story Points)
{{ decisions }}

## Технические вопросы
{{ technical_issues }}

## Готовые к спринту
{{ tasks }}

## Требуют дополнительной проработки
{{ action_items }}

## Следующий grooming
{{ next_steps }}"""
            }
        ]
    
    def get_all_templates(self) -> List[Dict[str, Any]]:
        """Все шаблоны библиотеки"""
        return (
            self.get_management_templates() +
            self.get_product_templates()
        )

