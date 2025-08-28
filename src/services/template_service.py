"""
Сервис для работы с шаблонами
"""

from typing import List, Dict, Any
from jinja2 import Environment, BaseLoader, TemplateError
from loguru import logger

from src.models.template import Template, TemplateCreate
from src.exceptions.template import TemplateNotFoundError, TemplateValidationError
from database import db


class TemplateService:
    """Сервис для работы с шаблонами"""
    
    def __init__(self):
        self.db = db
        self.jinja_env = Environment(loader=BaseLoader())
    
    async def get_all_templates(self) -> List[Template]:
        """Получить все шаблоны"""
        try:
            templates_data = await self.db.get_templates()
            return [Template(**template) for template in templates_data]
        except Exception as e:
            logger.error(f"Ошибка при получении шаблонов: {e}")
            raise
    
    async def get_template_by_id(self, template_id: int) -> Template:
        """Получить шаблон по ID"""
        try:
            template_data = await self.db.get_template(template_id)
            if not template_data:
                raise TemplateNotFoundError(template_id)
            
            return Template(**template_data)
        except TemplateNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Ошибка при получении шаблона {template_id}: {e}")
            raise
    
    async def create_template(self, template_data: TemplateCreate) -> Template:
        """Создать новый шаблон"""
        try:
            # Валидируем шаблон
            self.validate_template_content(template_data.content)
            
            # Создаем шаблон в БД
            template_id = await self.db.create_template(
                name=template_data.name,
                content=template_data.content,
                description=template_data.description,
                created_by=template_data.created_by,
                is_default=template_data.is_default
            )
            
            # Возвращаем созданный шаблон
            created_template = await self.get_template_by_id(template_id)
            logger.info(f"Создан новый шаблон: {template_data.name} (ID: {template_id})")
            return created_template
            
        except TemplateValidationError:
            raise
        except Exception as e:
            logger.error(f"Ошибка при создании шаблона {template_data.name}: {e}")
            raise
    
    def validate_template_content(self, content: str) -> None:
        """Валидировать содержимое шаблона"""
        try:
            # Проверяем валидность Jinja2 синтаксиса
            self.jinja_env.from_string(content)
        except TemplateError as e:
            raise TemplateValidationError(f"Некорректный синтаксис Jinja2: {e}", content)
        except Exception as e:
            raise TemplateValidationError(f"Ошибка валидации шаблона: {e}", content)
    
    def render_template(self, template_content: str, variables: Dict[str, Any]) -> str:
        """Отрендерить шаблон с переменными"""
        try:
            template = self.jinja_env.from_string(template_content)
            return template.render(**variables)
        except TemplateError as e:
            logger.error(f"Ошибка при рендеринге шаблона: {e}")
            raise TemplateValidationError(f"Ошибка рендеринга: {e}")
        except Exception as e:
            logger.error(f"Неожиданная ошибка при рендеринге шаблона: {e}")
            raise
    
    def extract_template_variables(self, template_content: str) -> List[str]:
        """Извлечь переменные из шаблона"""
        try:
            template = self.jinja_env.from_string(template_content)
            # Извлекаем все переменные из AST
            from jinja2 import meta
            variables = meta.find_undeclared_variables(template.environment.parse(template_content))
            return list(variables)
        except Exception as e:
            logger.warning(f"Не удалось извлечь переменные из шаблона: {e}")
            return []
    
    async def init_default_templates(self) -> None:
        """Инициализация базовых шаблонов"""
        try:
            # Проверяем, есть ли уже шаблоны
            existing_templates = await self.get_all_templates()
            if existing_templates:
                logger.info("Базовые шаблоны уже существуют, пропускаем инициализацию")
                return
            
            default_templates = self._get_default_templates()
            
            for template_data in default_templates:
                template_create = TemplateCreate(**template_data)
                await self.create_template(template_create)
            
            logger.info(f"Инициализировано {len(default_templates)} базовых шаблонов")
            
        except Exception as e:
            logger.error(f"Ошибка при инициализации базовых шаблонов: {e}")
            raise
    
    def _get_default_templates(self) -> List[Dict[str, Any]]:
        """Получить данные базовых шаблонов"""
        return [
            {
                "name": "Стандартный протокол встречи",
                "description": "Базовый шаблон для оформления протокола встречи",
                "content": """# Протокол встречи

## Основная информация
**Дата:** {{ date }}
**Время:** {{ time }}
**Участники:** {{ participants }}

{% if speakers_summary %}
## Анализ участников
{{ speakers_summary }}
{% endif %}

## Повестка дня
{{ agenda }}

## Обсуждение
{{ discussion }}

{% if speaker_contributions %}
## Вклад участников
{{ speaker_contributions }}
{% endif %}

## Принятые решения
{{ decisions }}

## Задачи и ответственные
{{ tasks }}

## Следующие шаги
{{ next_steps }}

---
*Протокол составлен автоматически с использованием диаризации*""",
                "is_default": True
            },
            {
                "name": "Краткое резюме встречи",
                "description": "Сокращенный формат для быстрого резюме",
                "content": """# Резюме встречи

**Участники:** {{ participants }}

## Ключевые моменты
{{ key_points }}

## Принятые решения
{{ decisions }}

## Дальнейшие действия
{{ action_items }}

{% if dialogue_analysis %}
## Анализ диалога
{{ dialogue_analysis }}
{% endif %}""",
                "is_default": True
            },
            {
                "name": "Техническое совещание",
                "description": "Шаблон для технических встреч и code review с диаризацией",
                "content": """# Техническое совещание

## Участники
{{ participants }}

{% if speaker_contributions %}
## Роли и экспертиза участников
{{ speaker_contributions }}
{% endif %}

## Рассмотренные вопросы
{{ technical_issues }}

## Архитектурные решения
{{ architecture_decisions }}

## Технические задачи
{{ technical_tasks }}

## Риски и блокеры
{{ risks_and_blockers }}

## Планы на следующий спринт
{{ next_sprint_plans }}

{% if dialogue_analysis %}
## Анализ технической дискуссии
{{ dialogue_analysis }}
{% endif %}""",
                "is_default": True
            },
            {
                "name": "Протокол с детализацией говорящих",
                "description": "Подробный шаблон с акцентом на диаризацию и вклад каждого участника",
                "content": """# Протокол встречи с анализом участников

## Основная информация
**Дата:** {{ date }}
**Время:** {{ time }}
**Участники:** {{ participants }}

## Краткая характеристика участников
{{ speakers_summary }}

## Повестка дня
{{ agenda }}

## Ход обсуждения
{{ discussion }}

## Анализ диалога и взаимодействия
{{ dialogue_analysis }}

## Вклад каждого участника
{{ speaker_contributions }}

## Принятые решения
{{ decisions }}

## Распределение задач и ответственности
{{ tasks }}

## Ключевые моменты и инсайты
{{ key_points }}

## Действия к выполнению
{{ action_items }}

## Следующие шаги
{{ next_steps }}

---
*Протокол создан автоматически с использованием AI-диаризации*""",
                "is_default": True
            }
        ]