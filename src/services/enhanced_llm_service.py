"""Enhanced LLM service — single-provider (OpenAI) with reliability stack."""

from typing import Any, Dict, Optional

from loguru import logger

from config import settings
from llm_providers import llm_manager
from src.exceptions.processing import LLMError
from src.reliability import (
    DEFAULT_CIRCUIT_BREAKER_CONFIG,
    LLM_RETRY_CONFIG,
    OPENAI_API_LIMIT,
    CircuitBreaker,
    CircuitBreakerConfig,
    RetryManager,
    create_llm_fallback_manager,
    global_rate_limiter,
)


class EnhancedLLMService:
    """LLM service with retry/circuit-breaker/rate-limit + cached-fallback safety net."""

    def __init__(self):
        self.llm_manager = llm_manager

        cb_config = CircuitBreakerConfig(
            failure_threshold=DEFAULT_CIRCUIT_BREAKER_CONFIG.failure_threshold,
            recovery_timeout=DEFAULT_CIRCUIT_BREAKER_CONFIG.recovery_timeout,
            success_threshold=DEFAULT_CIRCUIT_BREAKER_CONFIG.success_threshold,
            timeout=settings.llm_timeout_seconds,
        )
        self.retry_manager = RetryManager(LLM_RETRY_CONFIG)
        self.circuit_breaker = CircuitBreaker("openai_llm", cb_config)
        self.rate_limiter = global_rate_limiter.get_or_create(
            "openai_api", OPENAI_API_LIMIT
        )
        self.fallback_manager = create_llm_fallback_manager()
        self.fallback_manager.set_primary(self._generate_protocol_primary)

    async def _generate_protocol_primary(
        self,
        preset: Dict[str, Any],
        transcription: str,
        template_variables: Dict[str, str],
        diarization_data: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Primary path: rate-limit -> circuit-breaker -> retry -> manager."""
        await self.rate_limiter.acquire()

        async def protected_call():
            return await self.retry_manager.execute_with_retry(
                self.llm_manager.generate_protocol,
                preset=preset,
                transcription=transcription,
                template_variables=template_variables,
                diarization_data=diarization_data,
                **kwargs,
            )

        return await self.circuit_breaker.call(protected_call)

    async def generate_protocol_with_preset(
        self,
        preset: Dict[str, Any],
        transcription: str,
        template_variables: Dict[str, str],
        diarization_data: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Run LLM with cached fallback as a safety net."""
        cache_key = f"openai_{hash(transcription[:100])}"
        try:
            result = await self.fallback_manager.execute(
                preset,
                transcription,
                template_variables,
                diarization_data,
                cache_key=cache_key,
                **kwargs,
            )
            exec_info = getattr(self.fallback_manager, 'last_execution', {})
            if exec_info.get('mode') == 'fallback':
                logger.info(
                    f"Возвращён результат через fallback: "
                    f"{exec_info.get('fallback_name')}"
                )
            elif exec_info.get('mode') == 'cache':
                logger.info("Возвращён результат из кеша fallback-менеджера")
            return result
        except LLMError:
            raise
        except Exception as e:
            logger.error(f"LLM не сработал: {e}")
            raise LLMError(str(e), "openai", preset.get("model")) from e

    def get_reliability_stats(self) -> Dict[str, Any]:
        return {
            "fallback_manager": self.fallback_manager.get_stats(),
            "circuit_breaker": self.circuit_breaker.get_stats(),
            "rate_limiter": self.rate_limiter.get_stats(),
        }

    async def reset_reliability_components(self):
        await self.circuit_breaker.reset()
        self.fallback_manager.clear_cache()
        logger.info("Сброшены компоненты надежности LLM")
