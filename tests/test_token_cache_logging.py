"""
Тесты для утилит логирования кеширования токенов
"""

import pytest
from unittest.mock import Mock, MagicMock
from src.utils.token_cache_logger import (
    check_cache_support,
    log_cached_tokens_usage,
    format_cache_summary,
    _get_token_cost
)


class TestCheckCacheSupport:
    """Тесты для проверки поддержки кеширования"""
    
    def test_openai_gpt4o_supported(self):
        """GPT-4o поддерживает кеширование"""
        result = check_cache_support("gpt-4o", "openai")
        
        assert result["supported"] is True
        assert result["method"] == "automatic"
        assert result["min_tokens"] == 1024
        assert result["discount"] == 0.5
    
    def test_openai_gpt4o_mini_supported(self):
        """GPT-4o-mini поддерживает кеширование"""
        result = check_cache_support("gpt-4o-mini", "openai")
        
        assert result["supported"] is True
        assert result["method"] == "automatic"
        assert result["discount"] == 0.5
    
    def test_openai_gpt35_not_supported(self):
        """GPT-3.5-turbo не поддерживает кеширование"""
        result = check_cache_support("gpt-3.5-turbo", "openai")
        
        assert result["supported"] is False
        assert result["method"] is None
        assert result["discount"] == 0.0
    
    def test_anthropic_claude35_supported(self):
        """Claude 3.5 Sonnet поддерживает кеширование"""
        result = check_cache_support("claude-3-5-sonnet-20241022", "anthropic")
        
        assert result["supported"] is True
        assert result["method"] == "explicit"
        assert result["min_tokens"] == 1024
        assert result["discount"] == 0.9
    
    def test_anthropic_claude3_opus_supported(self):
        """Claude 3 Opus поддерживает кеширование"""
        result = check_cache_support("claude-3-opus-20240229", "anthropic")
        
        assert result["supported"] is True
        assert result["method"] == "explicit"
        assert result["discount"] == 0.9
    
    def test_unknown_provider_not_supported(self):
        """Неизвестный провайдер не поддерживает кеширование"""
        result = check_cache_support("unknown-model", "unknown")
        
        assert result["supported"] is False
        assert result["method"] is None


class TestGetTokenCost:
    """Тесты для расчета стоимости токенов"""
    
    def test_gpt4o_input_cost(self):
        """Стоимость input токенов для GPT-4o"""
        cost = _get_token_cost("gpt-4o", "input")
        assert cost == 0.0025
    
    def test_gpt4o_cached_cost(self):
        """Стоимость кешированных токенов для GPT-4o"""
        cost = _get_token_cost("gpt-4o", "cached_input")
        assert cost == 0.00125  # 50% скидка
    
    def test_gpt4o_mini_input_cost(self):
        """Стоимость input токенов для GPT-4o-mini"""
        cost = _get_token_cost("gpt-4o-mini", "input")
        assert cost == 0.00015
    
    def test_claude35_cached_cost(self):
        """Стоимость кешированных токенов для Claude 3.5"""
        cost = _get_token_cost("claude-3-5-sonnet-20241022", "cached_input")
        assert cost == 0.0003  # 90% скидка
    
    def test_unknown_model_fallback(self):
        """Неизвестная модель использует fallback на GPT-4o"""
        cost = _get_token_cost("unknown-model", "input")
        assert cost == 0.0025  # Fallback на gpt-4o


class TestLogCachedTokensUsage:
    """Тесты для логирования использования кешированных токенов"""
    
    def test_openai_with_cached_tokens(self):
        """OpenAI ответ с кешированными токенами"""
        # Создаем mock response
        mock_response = Mock()
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 20000
        mock_response.usage.completion_tokens = 3000
        mock_response.usage.total_tokens = 23000
        
        # Mock для prompt_tokens_details
        mock_details = Mock()
        mock_details.cached_tokens = 15000
        mock_response.usage.prompt_tokens_details = mock_details
        
        # Вызываем функцию
        metrics = log_cached_tokens_usage(
            response=mock_response,
            context="Test",
            model_name="gpt-4o",
            provider="openai"
        )
        
        # Проверяем метрики
        assert metrics["prompt_tokens"] == 20000
        assert metrics["completion_tokens"] == 3000
        assert metrics["total_tokens"] == 23000
        assert metrics["cached_tokens"] == 15000
        assert metrics["cache_hit_rate"] == 0.75  # 15000 / 20000
        assert metrics["cost_saved"] > 0
        assert metrics["savings_percent"] > 0
    
    def test_openai_without_cached_tokens(self):
        """OpenAI ответ без кешированных токенов"""
        mock_response = Mock()
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 20000
        mock_response.usage.completion_tokens = 3000
        mock_response.usage.total_tokens = 23000
        mock_response.usage.prompt_tokens_details = None
        
        metrics = log_cached_tokens_usage(
            response=mock_response,
            context="Test",
            model_name="gpt-4o",
            provider="openai"
        )
        
        assert metrics["cached_tokens"] == 0
        assert metrics["cache_hit_rate"] == 0.0
        assert metrics["cost_saved"] == 0.0
    
    def test_anthropic_with_cache_read(self):
        """Anthropic ответ с cache_read_input_tokens"""
        mock_response = Mock()
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 20000
        mock_response.usage.completion_tokens = 3000
        mock_response.usage.total_tokens = 23000
        mock_response.usage.cache_read_input_tokens = 18000
        mock_response.usage.cache_creation_input_tokens = 0
        
        metrics = log_cached_tokens_usage(
            response=mock_response,
            context="Test",
            model_name="claude-3-5-sonnet-20241022",
            provider="anthropic"
        )
        
        assert metrics["cached_tokens"] == 18000
        assert metrics["cache_hit_rate"] == 0.9  # 18000 / 20000
    
    def test_no_usage_in_response(self):
        """Response без usage информации"""
        mock_response = Mock(spec=[])  # No attributes
        
        metrics = log_cached_tokens_usage(
            response=mock_response,
            context="Test",
            provider="openai"
        )
        
        # Должны вернуться нулевые метрики
        assert metrics["prompt_tokens"] == 0
        assert metrics["cached_tokens"] == 0
        assert metrics["cache_hit_rate"] == 0.0
    
    def test_cost_calculation_accuracy(self):
        """Точность расчета стоимости"""
        mock_response = Mock()
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 10000
        mock_response.usage.completion_tokens = 2000
        mock_response.usage.total_tokens = 12000
        
        mock_details = Mock()
        mock_details.cached_tokens = 5000
        mock_response.usage.prompt_tokens_details = mock_details
        
        metrics = log_cached_tokens_usage(
            response=mock_response,
            context="Test",
            model_name="gpt-4o",
            provider="openai"
        )
        
        # Расчет вручную для GPT-4o:
        # Input: $0.0025 per 1K, Cached: $0.00125 per 1K, Output: $0.010 per 1K
        # Without cache: (10000/1000)*0.0025 + (2000/1000)*0.010 = 0.025 + 0.020 = 0.045
        # With cache: (5000/1000)*0.0025 + (5000/1000)*0.00125 + (2000/1000)*0.010 = 0.0125 + 0.00625 + 0.020 = 0.03875
        # Saved: 0.045 - 0.03875 = 0.00625
        
        assert abs(metrics["cost_without_cache"] - 0.045) < 0.001
        assert abs(metrics["cost_with_cache"] - 0.03875) < 0.001
        assert abs(metrics["cost_saved"] - 0.00625) < 0.001
        assert abs(metrics["savings_percent"] - 13.89) < 0.5  # ~13.89%


class TestFormatCacheSummary:
    """Тесты для форматирования сводки по кешированию"""
    
    def test_summary_with_multiple_metrics(self):
        """Сводка для нескольких запросов"""
        metrics_list = [
            {
                "prompt_tokens": 20000,
                "completion_tokens": 3000,
                "cached_tokens": 15000,
                "cost_saved": 0.0375,
                "cost_with_cache": 0.0375,
                "cost_without_cache": 0.075
            },
            {
                "prompt_tokens": 13000,
                "completion_tokens": 2500,
                "cached_tokens": 10000,
                "cost_saved": 0.025,
                "cost_with_cache": 0.025,
                "cost_without_cache": 0.05
            }
        ]
        
        summary = format_cache_summary(metrics_list)
        
        # Проверяем что сводка содержит ключевую информацию
        assert "33,000" in summary  # Total prompt tokens (20000 + 13000)
        assert "25,000" in summary  # Total cached tokens (15000 + 10000)
        assert "75.8" in summary or "76" in summary  # Cache rate % (25000/33000)
        assert "$0.0625" in summary  # Total cost saved (0.0375 + 0.025)
    
    def test_summary_with_empty_list(self):
        """Сводка для пустого списка"""
        summary = format_cache_summary([])
        
        assert "Нет данных" in summary
    
    def test_summary_formatting(self):
        """Проверка форматирования сводки"""
        metrics_list = [
            {
                "prompt_tokens": 10000,
                "completion_tokens": 1000,
                "cached_tokens": 5000,
                "cost_saved": 0.01,
                "cost_with_cache": 0.02,
                "cost_without_cache": 0.03
            }
        ]
        
        summary = format_cache_summary(metrics_list)
        
        # Проверяем структуру
        assert "📊 Сводка по кешированию токенов:" in summary
        assert "Всего запросов: 1" in summary
        assert "Токены:" in summary
        assert "Кешировано:" in summary
        assert "Стоимость:" in summary
        assert "Экономия:" in summary


class TestEdgeCases:
    """Тесты для граничных случаев"""
    
    def test_zero_prompt_tokens(self):
        """Нулевое количество prompt токенов"""
        mock_response = Mock()
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 0
        mock_response.usage.completion_tokens = 1000
        mock_response.usage.total_tokens = 1000
        mock_response.usage.prompt_tokens_details = None
        
        metrics = log_cached_tokens_usage(
            response=mock_response,
            context="Test",
            provider="openai"
        )
        
        assert metrics["cache_hit_rate"] == 0.0  # Не должно быть division by zero
    
    def test_cached_more_than_total(self):
        """Кешированных токенов больше чем total (некорректные данные)"""
        mock_response = Mock()
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 10000
        mock_response.usage.completion_tokens = 1000
        mock_response.usage.total_tokens = 11000
        
        mock_details = Mock()
        mock_details.cached_tokens = 15000  # Больше чем prompt_tokens!
        mock_response.usage.prompt_tokens_details = mock_details
        
        # Не должно вызывать ошибку
        metrics = log_cached_tokens_usage(
            response=mock_response,
            context="Test",
            provider="openai"
        )
        
        assert metrics["cached_tokens"] == 15000
        assert metrics["cache_hit_rate"] == 1.5  # Некорректное значение, но не краш
    
    def test_model_name_case_insensitive(self):
        """Название модели регистронезависимо"""
        result1 = check_cache_support("GPT-4O", "openai")
        result2 = check_cache_support("gpt-4o", "openai")
        result3 = check_cache_support("GpT-4O", "openai")
        
        assert result1["supported"] == result2["supported"] == result3["supported"]
        assert result1["discount"] == result2["discount"] == result3["discount"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

