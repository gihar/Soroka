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
    
    async def get_user_templates(self, telegram_id: int) -> List[Template]:
        """Получить шаблоны пользователя"""
        try:
            templates_data = await self.db.get_user_templates(telegram_id)
            return [Template(**template) for template in templates_data]
        except Exception as e:
            logger.error(f"Ошибка при получении шаблонов пользователя {telegram_id}: {e}")
            raise
    
    async def set_user_default_template(self, telegram_id: int, template_id: int) -> bool:
        """Установить шаблон по умолчанию для пользователя"""
        try:
            result = await self.db.set_user_default_template(telegram_id, template_id)
            if result:
                logger.info(f"Установлен шаблон по умолчанию {template_id} для пользователя {telegram_id}")
            return result
        except Exception as e:
            logger.error(f"Ошибка при установке шаблона по умолчанию для пользователя {telegram_id}: {e}")
            raise

    async def reset_user_default_template(self, telegram_id: int) -> bool:
        """Сбросить шаблон по умолчанию для пользователя"""
        try:
            result = await self.db.reset_user_default_template(telegram_id)
            if result:
                logger.info(f"Сброшен шаблон по умолчанию для пользователя {telegram_id}")
            return result
        except Exception as e:
            logger.error(f"Ошибка при сбросе шаблона по умолчанию для пользователя {telegram_id}: {e}")
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
                is_default=template_data.is_default,
                category=template_data.category,
                tags=template_data.tags,
                keywords=template_data.keywords
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

    async def delete_template(self, telegram_id: int, template_id: int) -> bool:
        """Удалить шаблон пользователя (если не базовый)"""
        try:
            result = await self.db.delete_template(telegram_id, template_id)
            if result:
                logger.info(f"Пользователь {telegram_id} удалил шаблон {template_id}")
            return result
        except Exception as e:
            logger.error(f"Ошибка при удалении шаблона {template_id}: {e}")
            return False
    
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
    
    def _convert_dict_to_template(self, template_dict: Dict[str, Any]) -> Template:
        """Преобразовать словарь в объект Template"""
        return Template(**template_dict)
    
    async def init_default_templates(self) -> None:
        """Инициализация базовых и библиотечных шаблонов"""
        try:
            # Проверяем, есть ли уже шаблоны
            existing_templates = await self.get_all_templates()
            
            # Импортируем библиотеку шаблонов
            from src.services.template_library import TemplateLibrary
            
            # Объединяем базовые и библиотечные шаблоны
            library = TemplateLibrary()
            all_templates = self._get_default_templates() + library.get_all_templates()
            
            # Если уже есть достаточно шаблонов, пропускаем
            if len(existing_templates) >= len(all_templates):
                logger.info(f"Шаблоны уже инициализированы ({len(existing_templates)} шаблонов)")
                return
            
            # Создаем только отсутствующие шаблоны
            existing_names = {t.name for t in existing_templates}
            templates_to_create = [t for t in all_templates if t["name"] not in existing_names]
            
            for template_data in templates_to_create:
                template_create = TemplateCreate(**template_data)
                await self.create_template(template_create)
            
            logger.info(f"Инициализировано {len(templates_to_create)} новых шаблонов")
            logger.info(f"Всего шаблонов в системе: {len(existing_templates) + len(templates_to_create)}")
            
        except Exception as e:
            logger.error(f"Ошибка при инициализации шаблонов: {e}")
            raise
    
    def _get_default_templates(self) -> List[Dict[str, Any]]:
        """Получить данные базовых шаблонов"""
        return [
            {
                "name": "Стандартный протокол встречи",
                "description": "Базовый шаблон для оформления протокола встречи",
                "category": "general",
                "tags": ["general", "meeting"],
                "keywords": ["встреча", "протокол", "общий"],
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
                "category": "general",
                "tags": ["brief", "summary"],
                "keywords": ["резюме", "краткое", "summary"],
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
                "category": "technical",
                "tags": ["technical", "engineering", "code_review"],
                "keywords": ["техническое", "разработка", "код", "архитектура"],
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
                "category": "general",
                "tags": ["detailed", "diarization"],
                "keywords": ["детализация", "участники", "диаризация", "спикеры"],
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
