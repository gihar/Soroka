"""
Утилиты для логирования и мониторинга prompt caching в LLM запросах
"""

from typing import Any, Dict, Optional

from loguru import logger

# Стоимость токенов для различных моделей (USD за 1K токенов)
TOKEN_COSTS = {
    # OpenAI
    "gpt-4o": {"input": 0.0025, "output": 0.010, "cached_input": 0.00125},  # 50% скидка
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006, "cached_input": 0.000075},  # 50% скидка
    "gpt-4-turbo": {"input": 0.010, "output": 0.030, "cached_input": 0.005},  # 50% скидка
    "gpt-4": {"input": 0.030, "output": 0.060, "cached_input": 0.015},  # 50% скидка
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015, "cached_input": 0.0005},  # Не поддерживает кеширование
    
    # Anthropic
    "claude-3-5-sonnet-20241022": {"input": 0.003, "output": 0.015, "cached_input": 0.0003},  # 90% скидка
    "claude-3-5-sonnet-20240620": {"input": 0.003, "output": 0.015, "cached_input": 0.0003},  # 90% скидка
    "claude-3-opus-20240229": {"input": 0.015, "output": 0.075, "cached_input": 0.0015},  # 90% скидка
    "claude-3-sonnet-20240229": {"input": 0.003, "output": 0.015, "cached_input": 0.0003},  # 90% скидка
}


def check_cache_support(model_name: str, provider: str) -> Dict[str, Any]:
    """
    Проверить, поддерживает ли модель prompt caching
    
    Args:
        model_name: Название модели (например, "gpt-4o", "claude-3-5-sonnet")
        provider: Провайдер API ("openai" или "anthropic")
        
    Returns:
        Словарь с информацией о поддержке кеширования:
        {
            "supported": bool,
            "method": str,  # "automatic" или "explicit"
            "min_tokens": int,
            "discount": float,  # Процент скидки (0.5 = 50%, 0.9 = 90%)
            "notes": str
        }
    """
    model_lower = model_name.lower()
    
    if provider == "openai":
        # OpenAI поддерживает автоматическое кеширование для определенных моделей
        if any(m in model_lower for m in ["gpt-4o", "gpt-4-turbo"]):
            return {
                "supported": True,
                "method": "automatic",
                "min_tokens": 1024,
                "discount": 0.5,  # 50% скидка
                "notes": "OpenAI автоматически кеширует префиксы промптов >= 1024 токенов"
            }
        elif "gpt-4" in model_lower and "vision" not in model_lower:
            return {
                "supported": True,
                "method": "automatic",
                "min_tokens": 1024,
                "discount": 0.5,  # 50% скидка
                "notes": "OpenAI автоматически кеширует префиксы промптов >= 1024 токенов"
            }
        else:
            return {
                "supported": False,
                "method": None,
                "min_tokens": 0,
                "discount": 0.0,
                "notes": f"Модель {model_name} не поддерживает prompt caching"
            }
    
    elif provider == "anthropic":
        # Anthropic поддерживает явное кеширование для Claude 3 моделей
        if "claude-3" in model_lower or "claude-3.5" in model_lower:
            return {
                "supported": True,
                "method": "explicit",
                "min_tokens": 1024,
                "discount": 0.9,  # 90% скидка
                "notes": "Anthropic требует явных cache_control маркеров. Минимум 1024 токена для кеширования."
            }
        else:
            return {
                "supported": False,
                "method": None,
                "min_tokens": 0,
                "discount": 0.0,
                "notes": f"Модель {model_name} не поддерживает prompt caching"
            }
    
    else:
        return {
            "supported": False,
            "method": None,
            "min_tokens": 0,
            "discount": 0.0,
            "notes": f"Провайдер {provider} не поддерживает prompt caching"
        }


def _get_token_cost(model_name: str, token_type: str) -> float:
    """
    Получить стоимость токенов для модели
    
    Args:
        model_name: Название модели
        token_type: "input", "output" или "cached_input"
        
    Returns:
        Стоимость за 1K токенов в USD
    """
    model_lower = model_name.lower()
    
    # Пытаемся найти точное совпадение
    if model_lower in TOKEN_COSTS:
        return TOKEN_COSTS[model_lower].get(token_type, 0.0)
    
    # Пытаемся найти по частичному совпадению
    for model_key, costs in TOKEN_COSTS.items():
        if model_key in model_lower:
            return costs.get(token_type, 0.0)
    
    # Fallback - возвращаем стоимость gpt-4o как базовую
    return TOKEN_COSTS.get("gpt-4o", {}).get(token_type, 0.0)


def log_cached_tokens_usage(
    response: Any,
    context: str = "",
    model_name: Optional[str] = None,
    provider: str = "openai"
) -> Dict[str, Any]:
    """
    Логировать использование кешированных токенов из ответа API
    
    Args:
        response: Ответ от OpenAI/Anthropic API с usage информацией
        context: Контекст вызова (например, "Stage 1", "Unified")
        model_name: Название модели для расчета стоимости
        provider: Провайдер API ("openai" или "anthropic")
        
    Returns:
        Словарь с метриками:
        {
            "prompt_tokens": int,
            "completion_tokens": int,
            "total_tokens": int,
            "cached_tokens": int,
            "cache_hit_rate": float,  # 0.0 - 1.0
            "cost_without_cache": float,
            "cost_with_cache": float,
            "cost_saved": float,
            "savings_percent": float
        }
    """
    metrics = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cached_tokens": 0,
        "cache_hit_rate": 0.0,
        "cost_without_cache": 0.0,
        "cost_with_cache": 0.0,
        "cost_saved": 0.0,
        "savings_percent": 0.0
    }
    
    # Извлекаем usage информацию
    if not hasattr(response, 'usage'):
        logger.debug(f"[{context}] Response не содержит usage информации")
        return metrics
    
    usage = response.usage
    
    # Базовые метрики
    metrics["prompt_tokens"] = getattr(usage, 'prompt_tokens', 0) or 0
    metrics["completion_tokens"] = getattr(usage, 'completion_tokens', 0) or 0
    metrics["total_tokens"] = getattr(usage, 'total_tokens', 0) or 0
    
    # Извлекаем информацию о кешированных токенах
    cached_tokens = 0
    
    # OpenAI: prompt_tokens_details.cached_tokens
    if hasattr(usage, 'prompt_tokens_details') and usage.prompt_tokens_details:
        details = usage.prompt_tokens_details
        
        # Проверяем различные возможные поля
        if hasattr(details, 'cached_tokens'):
            cached_tokens = getattr(details, 'cached_tokens', 0) or 0
        elif hasattr(details, 'cached_prompt_tokens'):
            cached_tokens = getattr(details, 'cached_prompt_tokens', 0) or 0
    
    # Anthropic: cache_creation_input_tokens + cache_read_input_tokens
    if provider == "anthropic":
        cache_read = getattr(usage, 'cache_read_input_tokens', 0) or 0
        cache_creation = getattr(usage, 'cache_creation_input_tokens', 0) or 0
        cached_tokens = cache_read
        
        if cache_creation > 0:
            logger.debug(f"[{context}] Создано кеша: {cache_creation} токенов")
    
    metrics["cached_tokens"] = cached_tokens
    
    # Рассчитываем cache hit rate
    if metrics["prompt_tokens"] > 0:
        metrics["cache_hit_rate"] = cached_tokens / metrics["prompt_tokens"]
    
    # Рассчитываем стоимость
    if model_name:
        input_cost_per_k = _get_token_cost(model_name, "input")
        output_cost_per_k = _get_token_cost(model_name, "output")
        cached_cost_per_k = _get_token_cost(model_name, "cached_input")
        
        # Стоимость без кеширования
        uncached_prompt_tokens = metrics["prompt_tokens"]
        metrics["cost_without_cache"] = (
            (uncached_prompt_tokens / 1000) * input_cost_per_k +
            (metrics["completion_tokens"] / 1000) * output_cost_per_k
        )
        
        # Стоимость с кешированием
        regular_prompt_tokens = metrics["prompt_tokens"] - cached_tokens
        metrics["cost_with_cache"] = (
            (regular_prompt_tokens / 1000) * input_cost_per_k +
            (cached_tokens / 1000) * cached_cost_per_k +
            (metrics["completion_tokens"] / 1000) * output_cost_per_k
        )
        
        # Экономия
        metrics["cost_saved"] = metrics["cost_without_cache"] - metrics["cost_with_cache"]
        
        if metrics["cost_without_cache"] > 0:
            metrics["savings_percent"] = (metrics["cost_saved"] / metrics["cost_without_cache"]) * 100
    
    # Логирование
    context_prefix = f"[{context}] " if context else ""
    
    logger.info(
        f"{context_prefix}Токены: prompt={metrics['prompt_tokens']}, "
        f"completion={metrics['completion_tokens']}, total={metrics['total_tokens']}"
    )
    
    if cached_tokens > 0:
        logger.info(
            f"{context_prefix}💰 Кешировано: {cached_tokens} токенов "
            f"({metrics['cache_hit_rate']:.1%} от prompt)"
        )
        
        if model_name and metrics["cost_saved"] > 0:
            logger.info(
                f"{context_prefix}💵 Экономия: ${metrics['cost_saved']:.4f} "
                f"({metrics['savings_percent']:.1f}%) | "
                f"Стоимость: ${metrics['cost_with_cache']:.4f} вместо ${metrics['cost_without_cache']:.4f}"
            )
    elif metrics["prompt_tokens"] >= 1024:
        # Кеша нет, хотя токенов достаточно - возможная проблема
        logger.debug(
            f"{context_prefix}⚠️ Кешированных токенов нет, хотя prompt >= 1024 токенов. "
            f"Возможно, это первый запрос с таким промптом или модель не поддерживает caching."
        )
    
    return metrics


def format_cache_summary(metrics_list: list[Dict[str, Any]]) -> str:
    """
    Форматировать сводку по кешированию для нескольких запросов
    
    Args:
        metrics_list: Список метрик от log_cached_tokens_usage
        
    Returns:
        Отформатированная строка со сводкой
    """
    if not metrics_list:
        return "Нет данных о кешировании"
    
    total_prompt = sum(m["prompt_tokens"] for m in metrics_list)
    total_completion = sum(m["completion_tokens"] for m in metrics_list)
    total_cached = sum(m["cached_tokens"] for m in metrics_list)
    total_cost_saved = sum(m["cost_saved"] for m in metrics_list)
    total_cost_with = sum(m["cost_with_cache"] for m in metrics_list)
    total_cost_without = sum(m["cost_without_cache"] for m in metrics_list)
    
    cache_rate = (total_cached / total_prompt * 100) if total_prompt > 0 else 0
    savings_percent = (total_cost_saved / total_cost_without * 100) if total_cost_without > 0 else 0
    
    summary = [
        "📊 Сводка по кешированию токенов:",
        f"   Всего запросов: {len(metrics_list)}",
        f"   Токены: {total_prompt + total_completion:,} (prompt: {total_prompt:,}, completion: {total_completion:,})",
        f"   Кешировано: {total_cached:,} токенов ({cache_rate:.1f}% от prompt)",
    ]
    
    if total_cost_without > 0:
        summary.extend([
            f"   Стоимость: ${total_cost_with:.4f} (без кеша: ${total_cost_without:.4f})",
            f"   💰 Экономия: ${total_cost_saved:.4f} ({savings_percent:.1f}%)"
        ])
    
    return "\n".join(summary)

