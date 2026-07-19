"""
Библиотека системных шаблонов протоколов.

Единый источник структуры — брифы (``protocol_briefs``): content каждого
системного шаблона генерируется компилятором (``brief_compiler``) из брифа,
байт-в-байт равного прежнему тексту. Метаданные (имя, категория, теги, ключевые
слова) живут здесь.

Единая структура (см. PRODUCT.md и ADR о канальном рендере):
- шапка: название встречи ({{ meeting_title }} с фолбэком на тип), дата, участники;
- порядок секций: решения -> задачи/сроки -> блокеры -> спец-секции типа встречи
  -> обсуждение -> следующие шаги;
- эмодзи — только навигационные метки СКВОЗНЫХ секций (единый словарь:
  📋 повестка/структура, 👥 участники, ✅ решения, 📌 задачи и сроки,
  ⚠️ блокеры, 💡 ключевые выводы, 💬 обсуждение, ❓ вопросы, 📅 следующие
  шаги); спец-секции типа встречи — осознанно без меток;
- каждая секция обёрнута в {% if %}: пустая секция не оставляет заголовка;
- канонический формат — Markdown; представление под канал (Telegram HTML,
  .md-файл, PDF) — забота src.services.protocol_render.

Поле is_default — исторически «системный шаблон»: виден всем пользователям
(запрос created_by = ? OR is_default = 1) и защищён от удаления. Это НЕ
«шаблон по умолчанию» пользователя (тот хранится в users.default_template_id).
"""

from typing import Any, Dict, List

from src.services.brief_compiler import brief_to_template_content
from src.services.protocol_briefs import get_brief_for


def _content(template_name: str) -> str:
    """Jinja-контент системного шаблона, собранный из его брифа."""
    brief = get_brief_for(template_name)
    if brief is None:  # pragma: no cover - защита от рассинхронизации имён
        raise KeyError(f"Нет брифа для системного шаблона: {template_name!r}")
    return brief_to_template_content(brief)


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
            "content": _content("Стандартный протокол встречи"),
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
            "content": _content("Краткое резюме встречи"),
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
            "content": _content("Техническое совещание"),
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
            "content": _content("Протокол ОД (Поручения)"),
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
            "content": _content("Дейли"),
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
            "content": _content("Ретроспектива спринта"),
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
            "content": _content("Лекция и презентация"),
        }
