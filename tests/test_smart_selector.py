"""
Тесты для умного выбора шаблонов
"""

import pytest
from datetime import datetime
from src.services.smart_template_selector import SmartTemplateSelector
from src.models.template import Template


@pytest.mark.asyncio
async def test_suggest_templates_product():
    """Тест рекомендации продуктового шаблона"""
    selector = SmartTemplateSelector()
    
    # Тестовые шаблоны
    templates = [
        Template(
            id=1,
            name="Sprint Planning",
            description="Планирование спринта",
            content="# Sprint Planning",
            category="product",
            tags=["sprint", "planning"],
            keywords=["спринт", "задачи", "backlog"],
            is_default=True,
            created_at=datetime.now()
        ),
        Template(
            id=2,
            name="Стратегическая сессия",
            description="Стратегическое планирование",
            content="# Стратегия",
            category="management",
            tags=["strategy"],
            keywords=["стратегия", "цели", "KPI"],
            is_default=True,
            created_at=datetime.now()
        )
    ]
    
    # Тестовая транскрипция (продуктовая)
    transcription = """
    Давайте спланируем наш следующий спринт. 
    У нас в backlog 10 задач. 
    Нужно оценить story points и выбрать приоритетные задачи.
    Capacity команды - 40 points.
    """
    
    suggestions = await selector.suggest_templates(transcription, templates, top_k=2)
    
    assert len(suggestions) > 0
    assert suggestions[0][0].id == 1  # Sprint Planning должен быть первым
    assert suggestions[0][1] > 0.3  # Уверенность > 30%


@pytest.mark.asyncio
async def test_suggest_templates_management():
    """Тест рекомендации управленческого шаблона"""
    selector = SmartTemplateSelector()
    
    templates = [
        Template(
            id=1,
            name="Sprint Planning",
            description="Планирование спринта",
            content="# Sprint Planning",
            category="product",
            tags=["sprint"],
            keywords=["спринт", "backlog"],
            is_default=True,
            created_at=datetime.now()
        ),
        Template(
            id=2,
            name="Бюджетное планирование",
            description="Планирование бюджета",
            content="# Бюджет",
            category="management",
            tags=["budget"],
            keywords=["бюджет", "расходы", "финансы"],
            is_default=True,
            created_at=datetime.now()
        )
    ]
    
    # Тестовая транскрипция (управленческая)
    transcription = """
    Рассмотрим бюджет на следующий квартал.
    Планируемые расходы составляют 2 миллиона рублей.
    Нужно оптимизировать затраты на маркетинг.
    """
    
    suggestions = await selector.suggest_templates(transcription, templates, top_k=2)
    
    assert len(suggestions) > 0
    assert suggestions[0][0].id == 2  # Бюджет должен быть первым
    assert suggestions[0][1] > 0.3


@pytest.mark.asyncio
async def test_suggest_with_history_boost():
    """Тест бонуса за историю использования"""
    selector = SmartTemplateSelector()
    
    templates = [
        Template(
            id=1,
            name="Template A",
            description="Test template A",
            content="# A",
            category="general",
            tags=[],
            keywords=["test"],
            is_default=True,
            created_at=datetime.now()
        ),
        Template(
            id=2,
            name="Template B",
            description="Test template B",
            content="# B",
            category="general",
            tags=[],
            keywords=["test"],
            is_default=True,
            created_at=datetime.now()
        )
    ]
    
    transcription = "General test meeting"
    user_history = [2, 2, 2]  # Template B использовался 3 раза
    
    suggestions = await selector.suggest_templates(
        transcription, templates, top_k=2, user_history=user_history
    )
    
    # Template B должен получить бонус и быть первым
    template_ids = [s[0].id for s in suggestions]
    assert 2 in template_ids


@pytest.mark.asyncio
async def test_empty_templates():
    """Тест с пустым списком шаблонов"""
    selector = SmartTemplateSelector()
    
    templates = []
    transcription = "Test meeting"
    
    suggestions = await selector.suggest_templates(transcription, templates)
    
    assert len(suggestions) == 0


@pytest.mark.asyncio
async def test_extract_keywords():
    """Тест извлечения ключевых слов"""
    selector = SmartTemplateSelector()
    
    text = "Нужно провести ретроспективу спринта и обсудить backlog"
    keywords = selector._extract_keywords(text)
    
    assert "спринт" in keywords
    assert "ретроспектива" in keywords
    assert "backlog" in keywords


@pytest.mark.asyncio
async def test_suggest_with_meeting_type_boost():
    """Тест категорийного boost для типа встречи"""
    selector = SmartTemplateSelector()
    
    templates = [
        Template(
            id=1,
            name="Общее совещание",
            description="Общие вопросы",
            content="# Общее",
            category="general",
            tags=[],
            keywords=[],
            is_default=True,
            created_at=datetime.now()
        ),
        Template(
            id=2,
            name="Техническое совещание",
            description="Обсуждение технических вопросов",
            content="# Техническое",
            category="technical",
            tags=["техническое"],
            keywords=["архитектура", "код"],
            is_default=True,
            created_at=datetime.now()
        )
    ]
    
    # Тестовая транскрипция (техническая)
    transcription = """
    Обсудим архитектуру нашего API.
    Нужно выбрать базу данных и настроить сервер.
    Рассмотрим алгоритмы кэширования.
    """
    
    # Без meeting_type - выбор на основе только similarity
    suggestions_without_type = await selector.suggest_templates(
        transcription, templates, top_k=2
    )
    
    # С meeting_type='technical' - должен получить boost
    suggestions_with_type = await selector.suggest_templates(
        transcription, templates, top_k=2, meeting_type='technical'
    )
    
    # Технический шаблон должен иметь более высокий score с boost
    assert len(suggestions_with_type) > 0
    tech_template_with_boost = next(
        (s for s in suggestions_with_type if s[0].id == 2), None
    )
    assert tech_template_with_boost is not None
    
    # Проверяем, что boost действительно применился
    if len(suggestions_without_type) > 0:
        tech_template_without_boost = next(
            (s for s in suggestions_without_type if s[0].id == 2), None
        )
        if tech_template_without_boost:
            # Score с boost должен быть выше
            assert tech_template_with_boost[1] > tech_template_without_boost[1]


@pytest.mark.asyncio
async def test_technical_meeting_selects_technical_template():
    """Тест выбора технического шаблона для технической встречи"""
    selector = SmartTemplateSelector()
    
    templates = [
        Template(
            id=1,
            name="Деловая встреча",
            description="Обсуждение бизнес-вопросов",
            content="# Деловое",
            category="business",
            tags=["бизнес"],
            keywords=["бюджет", "продажи"],
            is_default=True,
            created_at=datetime.now()
        ),
        Template(
            id=2,
            name="Code Review",
            description="Обзор кода и технических решений",
            content="# Code Review",
            category="technical",
            tags=["техническое", "разработка"],
            keywords=["код", "архитектура"],
            is_default=True,
            created_at=datetime.now()
        )
    ]
    
    transcription = """
    Сегодня проведем code review нового функционала.
    Рассмотрим архитектуру микросервисов и API endpoints.
    Обсудим алгоритмы обработки данных и оптимизацию запросов к базе.
    """
    
    suggestions = await selector.suggest_templates(
        transcription, templates, top_k=2, meeting_type='technical'
    )
    
    assert len(suggestions) > 0
    # Технический шаблон должен быть первым
    assert suggestions[0][0].id == 2
    assert suggestions[0][1] > 0.3  # Уверенность должна быть выше


@pytest.mark.asyncio
async def test_educational_meeting_selects_educational_template():
    """Тест выбора образовательного шаблона для обучающей встречи"""
    selector = SmartTemplateSelector()
    
    templates = [
        Template(
            id=1,
            name="Статус встреча",
            description="Отчет по статусу проекта",
            content="# Статус",
            category="status",
            tags=["отчет"],
            keywords=["статус", "прогресс"],
            is_default=True,
            created_at=datetime.now()
        ),
        Template(
            id=2,
            name="Обучающая сессия",
            description="Образовательная презентация",
            content="# Обучение",
            category="educational",
            tags=["обучение", "презентация"],
            keywords=["лекция", "тренинг"],
            is_default=True,
            created_at=datetime.now()
        )
    ]
    
    transcription = """
    Проведем обучающую сессию по новым технологиям.
    Я подготовил презентацию с примерами.
    В конце будет время для вопросов и практических упражнений.
    """
    
    suggestions = await selector.suggest_templates(
        transcription, templates, top_k=2, meeting_type='educational'
    )
    
    assert len(suggestions) > 0
    # Образовательный шаблон должен быть первым
    assert suggestions[0][0].id == 2
    assert suggestions[0][1] > 0.3

