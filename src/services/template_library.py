"""
Библиотека системных шаблонов протоколов.

Единая структура (см. PRODUCT.md и ADR о канальном рендере):
- шапка: название встречи ({{ meeting_title }} с фолбэком на тип), дата, участники;
- порядок секций: решения -> задачи/сроки -> блокеры -> спец-секции типа встречи
  -> обсуждение -> следующие шаги;
- эмодзи — только навигационные метки секций: 👥 ✅ 📌 ⚠️ 💬 📅;
- каждая секция обёрнута в {% if %}: пустая секция не оставляет заголовка;
- канонический формат — Markdown; представление под канал (Telegram HTML,
  .md-файл, PDF) — забота src.services.protocol_render.

Поле is_default — исторически «системный шаблон»: виден всем пользователям
(запрос created_by = ? OR is_default = 1) и защищён от удаления. Это НЕ
«шаблон по умолчанию» пользователя (тот хранится в users.default_template_id).
"""

from typing import Any, Dict, List

_HEADER = """{% if date %}**Дата:** {{ date }}{% if time %} · {{ time }}{% endif %}
{% endif %}{% if participants %}**👥 Участники:**
{{ participants }}
{% endif %}"""


class TemplateLibrary:
    """Системные шаблоны протоколов"""

    def get_all_templates(self) -> List[Dict[str, Any]]:
        """Все системные шаблоны"""
        return [
            self._standard_protocol(),
            self._brief_summary(),
            self._technical_meeting(),
            self._od_protocol(),
            self._daily(),
            self._retrospective(),
            self._lecture(),
        ]

    @staticmethod
    def _standard_protocol() -> Dict[str, Any]:
        return {
            "name": "Стандартный протокол встречи",
            "category": "general",
            "description": "Базовый шаблон для оформления протокола встречи",
            "tags": ["general", "meeting"],
            "keywords": ["встреча", "протокол", "общий"],
            "is_default": True,
            "content": """# {{ meeting_title or 'Протокол встречи' }}

"""
            + _HEADER
            + """
{% if agenda %}
## Повестка дня
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
## Ключевые выводы
{{ key_points }}
{% endif %}
{% if discussion %}
## 💬 Обсуждение
{{ discussion }}
{% endif %}
{% if questions %}
## Открытые вопросы
{{ questions }}
{% endif %}
{% if next_steps %}
## 📅 Следующие шаги
{{ next_steps }}
{% endif %}""",
        }

    @staticmethod
    def _brief_summary() -> Dict[str, Any]:
        return {
            "name": "Краткое резюме встречи",
            "category": "general",
            "description": "Сокращенный формат для быстрого резюме",
            "tags": ["brief", "summary"],
            "keywords": ["резюме", "краткое", "summary"],
            "is_default": True,
            "content": """# {{ meeting_title or 'Резюме встречи' }}

"""
            + _HEADER
            + """
{% if decisions %}
## ✅ Решения
{{ decisions }}
{% endif %}
{% if action_items %}
## 📌 Задачи и сроки
{{ action_items }}
{% endif %}
{% if key_points %}
## Ключевые выводы
{{ key_points }}
{% endif %}
{% if next_steps %}
## 📅 Следующие шаги
{{ next_steps }}
{% endif %}""",
        }

    @staticmethod
    def _technical_meeting() -> Dict[str, Any]:
        return {
            "name": "Техническое совещание",
            "category": "technical",
            "description": "Шаблон для технических встреч и code review с диаризацией",
            "tags": ["technical", "engineering", "code_review"],
            "keywords": ["техническое", "разработка", "код", "архитектура"],
            "is_default": True,
            "content": """# {{ meeting_title or 'Техническое совещание' }}

"""
            + _HEADER
            + """
{% if agenda %}
## Повестка дня
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
{% endif %}""",
        }

    @staticmethod
    def _od_protocol() -> Dict[str, Any]:
        return {
            "id": "od_protocol",
            "name": "Протокол ОД (Поручения)",
            "category": "management",
            "description": "Специальный формат для протокола поручений руководителей (OD)",
            "tags": ["поручения", "од", "руководители", "протокол"],
            "keywords": ["од", "поручение", "задача", "срок", "ответственный"],
            "is_default": True,
            "content": """# {{ meeting_title or 'Протокол поручений' }}

"""
            + _HEADER
            + """
{% if tasks_od %}
## 📌 Поручения
{{ tasks_od }}
{% else %}
Поручений в записи не зафиксировано.
{% endif %}
{% if additional_notes %}
## Дополнительные заметки
{{ additional_notes }}
{% endif %}""",
        }

    @staticmethod
    def _daily() -> Dict[str, Any]:
        return {
            "name": "Дейли",
            "category": "general",
            "description": "Ежедневные короткие встречи команды",
            "tags": ["daily", "scrum"],
            "keywords": ["standup", "вчера", "сегодня", "блокеры", "ежедневно"],
            "is_default": True,
            "content": """# {{ meeting_title or 'Дейли' }}

"""
            + _HEADER
            + """
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
{% endif %}""",
        }

    @staticmethod
    def _retrospective() -> Dict[str, Any]:
        return {
            "name": "Ретроспектива спринта",
            "category": "general",
            "description": "Ретроспектива спринта для улучшения процессов",
            "tags": ["retrospective", "agile", "improvement"],
            "keywords": ["ретроспектива", "что хорошо", "что улучшить", "действия", "retro"],
            "is_default": True,
            "content": """# {{ meeting_title or 'Ретроспектива спринта' }}

"""
            + _HEADER
            + """
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
{% endif %}""",
        }

    @staticmethod
    def _lecture() -> Dict[str, Any]:
        return {
            "id": "education_lecture",
            "name": "Лекция и презентация",
            "category": "educational",
            "description": "Шаблон для лекций и презентаций с фокусом на структуре материала",
            "tags": ["лекция", "презентация", "теория", "концепции"],
            "keywords": [
                "лекция", "презентация", "теория", "концепции",
                "определения", "примеры", "материал",
            ],
            "is_default": True,
            "content": """# {{ meeting_title or 'Лекция' }}

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
## Структура лекции
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
## Вопросы и ответы
{{ questions_and_answers }}
{% endif %}
{% if key_points %}
## Ключевые выводы
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
{% endif %}""",
        }
