"""
Сервис для работы с шаблонами
"""

from typing import List, Dict, Any, Optional
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
        # Если уже Template, возвращаем как есть
        if isinstance(template_dict, Template):
            return template_dict
        return Template(**template_dict)
    
    async def init_default_templates(self) -> None:
        """Создание и автообновление базовых шаблонов"""
        try:
            # Гарантируем, что схема таблицы templates поддерживает auto-update
            await self.db.ensure_templates_updated_at_column()
            existing_templates = await self.get_all_templates()
            existing_by_name: Dict[str, Template] = {}
            for template in existing_templates:
                stored = existing_by_name.get(template.name)
                if not stored:
                    existing_by_name[template.name] = template
                    continue
                if not self._is_system_template(stored) and self._is_system_template(template):
                    existing_by_name[template.name] = template
            
            from src.services.template_library import TemplateLibrary
            library = TemplateLibrary()
            target_templates = self._get_default_templates() + library.get_all_templates()
            
            created_count = 0
            updated_count = 0
            skipped_user_templates = 0
            
            for template_data in target_templates:
                template_name = template_data["name"]
                existing_template = existing_by_name.get(template_name)
                
                if not existing_template:
                    template_create = TemplateCreate(**template_data)
                    await self.create_template(template_create)
                    created_count += 1
                    continue
                
                if not self._is_system_template(existing_template):
                    skipped_user_templates += 1
                    continue
                
                if self._template_needs_update(existing_template, template_data):
                    await self._update_system_template(existing_template, template_data)
                    updated_count += 1
            
            total_templates = len(existing_templates) + created_count
            logger.info(
                "Синхронизация стандартных шаблонов завершена: создано %s, обновлено %s, пропущено пользовательских %s",
                created_count,
                updated_count,
                skipped_user_templates,
            )
            logger.info(f"Всего шаблонов в системе: {total_templates}")
        except Exception as e:
            logger.error(f"Ошибка при инициализации шаблонов: {e}")
            raise
    
    def _get_default_templates(self) -> List[Dict[str, Any]]:
        """Получить данные базовых шаблонов"""
        return [
            {
                "name": "Стандартный протокол встречи",
                "description": "Базовый шаблон для оформления протокола встречи",
                "tags": ["general", "meeting"],
                "keywords": ["встреча", "протокол", "общий"],
                "content": """# Протокол встречи

## Основная информация
{% if date %}**Дата:** {{ date }}
{% endif %}{% if time %}**Время:** {{ time }}
{% endif %}**Участники:** {{ participants }}

{% if agenda %}
## Повестка дня
{{ agenda }}
{% endif %}

{% if discussion %}
## Обсуждение
{{ discussion }}
{% endif %}

{% if speakers_summary %}
## Анализ участников
{{ speakers_summary }}
{% endif %}

{% if speaker_contributions %}
## Вклад участников
{{ speaker_contributions }}
{% endif %}

{% if decisions %}
## Принятые решения
{{ decisions }}
{% endif %}

{% if tasks %}
## Задачи и ответственные
{{ tasks }}
{% endif %}

{% if action_items %}
## Действия к выполнению
{{ action_items }}
{% endif %}

{% if next_steps %}
## Следующие шаги
{{ next_steps }}
{% endif %}

{% if deadlines %}
## Сроки
{{ deadlines }}
{% endif %}

{% if key_points %}
## Ключевые моменты
{{ key_points }}
{% endif %}

{% if issues %}
## Проблемы и вопросы
{{ issues }}
{% endif %}

---
*Протокол составлен автоматически*""",
                "is_default": True
            },
            {
                "name": "Краткое резюме встречи",
                "description": "Сокращенный формат для быстрого резюме",
                "tags": ["brief", "summary"],
                "keywords": ["резюме", "краткое", "summary"],
                "content": """# Резюме встречи

**Участники:** {{ participants }}

{% if key_points %}
## Ключевые моменты
{{ key_points }}
{% endif %}

{% if decisions %}
## Принятые решения
{{ decisions }}
{% endif %}

{% if action_items %}
## Дальнейшие действия
{{ action_items }}
{% endif %}

{% if dialogue_analysis %}
## Анализ диалога
{{ dialogue_analysis }}
{% endif %}

{% if next_steps %}
## Следующие шаги
{{ next_steps }}
{% endif %}""",
                "is_default": True
            },
            {
                "name": "Техническое совещание",
                "description": "Шаблон для технических встреч и code review с диаризацией",
                "tags": ["technical", "engineering", "code_review"],
                "keywords": ["техническое", "разработка", "код", "архитектура"],
                "content": """# Техническое совещание

## Участники
{{ participants }}

{% if speaker_contributions %}
## Роли и экспертиза участников
{{ speaker_contributions }}
{% endif %}

{% if agenda %}
## Повестка дня
{{ agenda }}
{% endif %}

{% if discussion %}
## Обсуждение
{{ discussion }}
{% endif %}

{% if technical_issues %}
## Рассмотренные вопросы
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

{% if decisions %}
## Принятые решения
{{ decisions }}
{% endif %}

{% if risks_and_blockers %}
## Риски и блокеры
{{ risks_and_blockers }}
{% endif %}

{% if next_sprint_plans %}
## Планы на следующий спринт
{{ next_sprint_plans }}
{% endif %}

{% if dialogue_analysis %}
## Анализ технической дискуссии
{{ dialogue_analysis }}
{% endif %}""",
                "is_default": True
            },
        ]

    @staticmethod
    def _is_system_template(template: Template) -> bool:
        """Определить, можно ли безопасно обновлять шаблон"""
        return template.created_by in (None, 0) or template.is_default

    def _template_needs_update(self, existing: Template, new_data: Dict[str, Any]) -> bool:
        """Понять, отличается ли системный шаблон от эталона"""
        target_description = new_data["description"] if "description" in new_data else existing.description
        if (existing.description or "") != (target_description or ""):
            return True
        
        target_content = new_data.get("content", existing.content)
        if existing.content != target_content:
            return True
        
        target_category = new_data["category"] if "category" in new_data else existing.category
        if (existing.category or "") != (target_category or ""):
            return True
        
        target_is_default = bool(new_data["is_default"]) if "is_default" in new_data else existing.is_default
        if bool(existing.is_default) != target_is_default:
            return True
        
        target_tags = new_data["tags"] if "tags" in new_data else existing.tags
        if not self._lists_equal(existing.tags, target_tags):
            return True
        
        target_keywords = new_data["keywords"] if "keywords" in new_data else existing.keywords
        if not self._lists_equal(existing.keywords, target_keywords):
            return True
        
        return False

    @staticmethod
    def _lists_equal(first: Optional[List[str]], second: Optional[List[str]]) -> bool:
        """Нормализованное сравнение списков"""
        def normalize(value: Optional[List[str]]) -> List[str]:
            if not value:
                return []
            return list(sorted(value))
        
        return normalize(first) == normalize(second)

    async def _update_system_template(self, existing: Template, template_data: Dict[str, Any]) -> None:
        """Перезаписать шаблон актуальным содержимым"""
        await self.db.update_template(
            template_id=existing.id,
            name=template_data["name"],
            description=template_data.get("description"),
            content=template_data.get("content", existing.content),
            is_default=template_data.get("is_default", existing.is_default),
            category=template_data.get("category"),
            tags=template_data.get("tags"),
            keywords=template_data.get("keywords"),
        )
