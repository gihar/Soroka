"""
Улучшенный сервис для работы с LLM с повышенной надежностью
"""

import asyncio
from typing import Dict, Any, Optional
from loguru import logger

from src.models.llm import LLMRequest, LLMResponse, LLMProviderType
from src.exceptions.processing import LLMError
from src.reliability import (
    RetryManager, LLM_RETRY_CONFIG,
    CircuitBreaker, CircuitBreakerConfig, DEFAULT_CIRCUIT_BREAKER_CONFIG,
    RateLimiter, global_rate_limiter, OPENAI_API_LIMIT, ANTHROPIC_API_LIMIT,
    FallbackManager, create_llm_fallback_manager
)
from config import settings
from llm_providers import llm_manager


class EnhancedLLMService:
    """Улучшенный сервис для работы с LLM с повышенной надежностью"""
    
    def __init__(self):
        self.llm_manager = llm_manager
        
        # Инициализация компонентов надежности
        self._setup_reliability_components()
        
        # Fallback менеджер
        self.fallback_manager = create_llm_fallback_manager()
        self.fallback_manager.set_primary(self._generate_protocol_primary)
    
    def _setup_reliability_components(self):
        """Настройка компонентов надежности"""
        # Retry менеджеры для каждого провайдера
        self.retry_managers = {
            "openai": RetryManager(LLM_RETRY_CONFIG),
            "anthropic": RetryManager(LLM_RETRY_CONFIG),
            "yandex": RetryManager(LLM_RETRY_CONFIG)
        }
        
        # Circuit breakers для каждого провайдера
        # Используем конфигурацию на основе базовой, но с таймаутом из настроек
        cb_config = CircuitBreakerConfig(
            failure_threshold=DEFAULT_CIRCUIT_BREAKER_CONFIG.failure_threshold,
            recovery_timeout=DEFAULT_CIRCUIT_BREAKER_CONFIG.recovery_timeout,
            success_threshold=DEFAULT_CIRCUIT_BREAKER_CONFIG.success_threshold,
            timeout=settings.llm_timeout_seconds,
        )
        self.circuit_breakers = {
            "openai": CircuitBreaker("openai_llm", cb_config),
            "anthropic": CircuitBreaker("anthropic_llm", cb_config),
            "yandex": CircuitBreaker("yandex_llm", cb_config),
        }
        
        # Rate limiters для каждого провайдера
        self.rate_limiters = {
            "openai": global_rate_limiter.get_or_create("openai_api", OPENAI_API_LIMIT),
            "anthropic": global_rate_limiter.get_or_create("anthropic_api", ANTHROPIC_API_LIMIT),
            "yandex": global_rate_limiter.get_or_create("yandex_api", ANTHROPIC_API_LIMIT)  # Используем похожий лимит
        }
    
    def get_available_providers(self) -> Dict[str, str]:
        """Получить список доступных провайдеров с учетом Circuit Breaker"""
        all_providers = self.llm_manager.get_available_providers()
        available_providers = {}
        
        for provider_key, provider_name in all_providers.items():
            # Проверяем состояние Circuit Breaker
            circuit_breaker = self.circuit_breakers.get(provider_key)
            if circuit_breaker and circuit_breaker.state.value == "open":
                logger.warning(f"Провайдер {provider_key} заблокирован Circuit Breaker")
                continue
            
            available_providers[provider_key] = provider_name
        
        return available_providers
    
    async def _generate_protocol_primary(self, provider: str, transcription: str, 
                                       template_variables: Dict[str, str],
                                       diarization_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Основной метод генерации протокола с защитой"""
        # Проверяем rate limiter
        rate_limiter = self.rate_limiters.get(provider)
        if rate_limiter:
            await rate_limiter.acquire()
        
        # Выполняем через Circuit Breaker и Retry
        circuit_breaker = self.circuit_breakers.get(provider)
        retry_manager = self.retry_managers.get(provider)
        
        if circuit_breaker and retry_manager:
            # Комбинируем Circuit Breaker и Retry
            async def protected_call():
                return await retry_manager.execute_with_retry(
                    self.llm_manager.generate_protocol,
                    provider, transcription, template_variables, diarization_data
                )
            
            return await circuit_breaker.call(protected_call)
        else:
            # Fallback к прямому вызову
            return await self.llm_manager.generate_protocol(
                provider, transcription, template_variables, diarization_data
            )
    
    async def generate_protocol(self, request: LLMRequest) -> LLMResponse:
        """Генерировать протокол с полной защитой"""
        try:
            provider = request.provider.value
            
            if provider not in self.get_available_providers():
                raise LLMError(f"Провайдер {provider} недоступен", provider)
            
            logger.info(f"Генерация протокола с провайдером: {provider}")
            
            # Создаем cache key для fallback
            cache_key = f"{provider}_{hash(request.transcription[:100])}"
            
            extracted_data = await self.fallback_manager.execute(
                provider,
                request.transcription,
                request.template_variables,
                request.diarization_data,
                cache_key=cache_key
            )
            
            response = LLMResponse(
                extracted_data=extracted_data,
                provider_used=provider,
                llm_model_used=request.model
            )
            
            exec_info = getattr(self.fallback_manager, 'last_execution', {})
            if exec_info.get('mode') == 'fallback':
                logger.info(f"Возвращён результат через fallback: {exec_info.get('fallback_name')}")
            elif exec_info.get('mode') == 'cache':
                logger.info("Возвращён результат из кеша fallback-менеджера")
            else:
                logger.info(f"Протокол успешно сгенерирован с провайдером: {provider}")
            return response
            
        except Exception as e:
            logger.error(f"Ошибка при генерации протокола с провайдером {request.provider.value}: {e}")
            raise LLMError(str(e), request.provider.value, request.model)
    
    async def generate_protocol_with_fallback(self, preferred_provider: str, transcription: str, 
                                            template_variables: Dict[str, str], 
                                            diarization_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Генерировать протокол с автоматическим переключением провайдеров"""
        available_providers = list(self.get_available_providers().keys())
        
        if not available_providers:
            # Используем fallback менеджер когда нет доступных провайдеров
            logger.warning("Нет доступных LLM провайдеров, используем fallback")
            cache_key = f"fallback_{hash(transcription[:100])}"
            return await self.fallback_manager.execute(
                None, transcription, template_variables, diarization_data,
                cache_key=cache_key
            )
        
        # Упорядочиваем провайдеры: предпочитаемый первым
        providers_to_try = []
        if preferred_provider in available_providers:
            providers_to_try.append(preferred_provider)
        
        for provider in available_providers:
            if provider not in providers_to_try:
                providers_to_try.append(provider)
        
        last_error = None
        
        for provider in providers_to_try:
            try:
                logger.info(f"Попытка генерации протокола с провайдером: {provider}")
                
                cache_key = f"{provider}_{hash(transcription[:100])}"
                result = await self.fallback_manager.execute(
                    provider, transcription, template_variables, diarization_data,
                    cache_key=cache_key
                )
                exec_info = getattr(self.fallback_manager, 'last_execution', {})
                if exec_info.get('mode') == 'fallback':
                    logger.info(f"Возвращён результат через fallback: {exec_info.get('fallback_name')}")
                elif exec_info.get('mode') == 'cache':
                    logger.info("Возвращён результат из кеша fallback-менеджера")
                else:
                    logger.info(f"Успешно сгенерирован протокол с провайдером: {provider}")
                return result
                
            except Exception as e:
                last_error = e
                logger.warning(f"Ошибка с провайдером {provider}: {e}")
                
                # Если это Circuit Breaker ошибка, не пытаемся повторно
                if "circuit breaker" in str(e).lower():
                    continue
                
                # Для других ошибок делаем небольшую паузу
                await asyncio.sleep(1)
                continue
        
        # Все провайдеры не сработали, используем fallback
        logger.error(f"Все провайдеры не сработали. Последняя ошибка: {last_error}")
        cache_key = f"final_fallback_{hash(transcription[:100])}"
        
        try:
            return await self.fallback_manager.execute(
                None, transcription, template_variables, diarization_data,
                cache_key=cache_key
            )
        except Exception as fallback_error:
            logger.error(f"Fallback также не сработал: {fallback_error}")
            raise LLMError(f"Все доступные провайдеры не сработали: {last_error}")
    
    def validate_provider(self, provider: str) -> bool:
        """Проверить доступность провайдера с учетом Circuit Breaker"""
        return provider in self.get_available_providers()
    
    def get_reliability_stats(self) -> Dict[str, Any]:
        """Получить статистику надежности"""
        stats = {
            "fallback_manager": self.fallback_manager.get_stats(),
            "circuit_breakers": {
                name: cb.get_stats() 
                for name, cb in self.circuit_breakers.items()
            },
            "rate_limiters": {
                name: rl.get_stats() 
                for name, rl in self.rate_limiters.items()
            }
        }
        
        return stats
    
    async def reset_reliability_components(self, provider: Optional[str] = None):
        """Сбросить компоненты надежности"""
        if provider:
            # Сбрасываем для конкретного провайдера
            if provider in self.circuit_breakers:
                await self.circuit_breakers[provider].reset()
                logger.info(f"Сброшен Circuit Breaker для {provider}")
        else:
            # Сбрасываем все
            for name, cb in self.circuit_breakers.items():
                await cb.reset()
            
            self.fallback_manager.clear_cache()
            logger.info("Сброшены все компоненты надежности")
