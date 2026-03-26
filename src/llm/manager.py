"""LLM provider manager with fallback support."""
from typing import Dict, Any, Optional
from loguru import logger

from src.llm.providers.openai_provider import OpenAIProvider
from src.llm.providers.anthropic_provider import AnthropicProvider
from src.llm.providers.yandex_provider import YandexGPTProvider


class LLMManager:
    """Manager for working with different LLM providers."""

    def __init__(self):
        self.providers = {
            "openai": OpenAIProvider(),
            "anthropic": AnthropicProvider(),
            "yandex": YandexGPTProvider()
        }

    def get_available_providers(self) -> Dict[str, str]:
        """Get list of available providers."""
        available = {}
        provider_names = {
            "openai": "OpenAI GPT",
            "anthropic": "Anthropic Claude",
            "yandex": "Yandex GPT"
        }

        for key, provider in self.providers.items():
            if provider.is_available():
                available[key] = provider_names[key]

        return available

    async def generate_protocol(self, provider_name: str, transcription: str,
                                template_variables: Dict[str, str],
                                diarization_data: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """Generate protocol using the specified provider."""
        if provider_name not in self.providers:
            raise ValueError(f"Неизвестный провайдер: {provider_name}")

        provider = self.providers[provider_name]
        if not provider.is_available():
            raise ValueError(f"Провайдер {provider_name} недоступен")

        return await provider.generate_protocol(transcription, template_variables, diarization_data, **kwargs)

    async def generate_protocol_with_fallback(self, preferred_provider: str = None, transcription: str = "",
                                              template_variables: Dict[str, str] = None,
                                              diarization_data: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """Generate protocol with fallback to other providers on failure."""
        available_providers = list(self.get_available_providers().keys())

        if not available_providers:
            raise ValueError("Нет доступных LLM провайдеров")

        providers_to_try = [preferred_provider] if preferred_provider in available_providers else []
        for provider in available_providers:
            if provider not in providers_to_try:
                providers_to_try.append(provider)

        last_error = None
        for provider_name in providers_to_try:
            try:
                logger.info(f"Попытка генерации протокола с провайдером: {provider_name}")
                result = await self.generate_protocol(provider_name, transcription, template_variables, diarization_data, **kwargs)
                logger.info(f"Успешно сгенерирован протокол с провайдером: {provider_name}")
                return result
            except Exception as e:
                last_error = e
                logger.warning(f"Ошибка с провайдером {provider_name}: {e}")
                continue

        raise ValueError(f"Все доступные провайдеры не сработали. Последняя ошибка: {last_error}")


async def generate_protocol(
    manager: 'LLMManager',
    provider_name: str,
    transcription: str,
    template_variables: Dict[str, str],
    diarization_data: Optional[Dict[str, Any]] = None,
    diarization_analysis: Optional[Dict[str, Any]] = None,
    participants_list: Optional[str] = None,
    meeting_metadata: Optional[Dict[str, str]] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Consolidated protocol generation method: wrapper around manager.

    Args:
        manager: LLM manager
        provider_name: Provider name
        transcription: Transcription text
        template_variables: Template variables
        diarization_data: Diarization data
        diarization_analysis: Diarization analysis
        participants_list: Participants list
        meeting_metadata: Meeting metadata
        **kwargs: Additional parameters

    Returns:
        Final protocol
    """
    original_participants = kwargs.get('participants')

    call_kwargs = kwargs.copy()

    if participants_list:
        if 'participants' not in call_kwargs:
            call_kwargs['participants'] = participants_list

    if meeting_metadata:
        call_kwargs.update(meeting_metadata)

    if diarization_analysis:
        call_kwargs['diarization_analysis'] = diarization_analysis

    if original_participants is not None:
        call_kwargs['participants'] = original_participants

    return await manager.generate_protocol(
        provider_name=provider_name,
        transcription=transcription,
        template_variables=template_variables,
        diarization_data=diarization_data,
        **call_kwargs
    )
