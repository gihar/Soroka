"""LLM provider manager — single-provider (OpenAI-compatible)."""
from typing import Dict, Any, Optional
from loguru import logger

from src.llm.providers.openai_provider import OpenAIProvider


class LLMManager:
    """Manager that delegates to a single OpenAI-compatible provider."""

    def __init__(self):
        self.providers = {"openai": OpenAIProvider()}

    async def generate_protocol(
        self,
        preset: Dict[str, Any],
        transcription: str,
        template_variables: Dict[str, str],
        diarization_data: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Generate a protocol using the given preset.

        `preset` is a fully resolved row from `model_presets` (dict with
        `key`, `model`, `base_url`, `api_key`, `name`). The provider receives it
        via `kwargs['preset']`.
        """
        provider = self.providers["openai"]
        if not provider.is_available():
            raise ValueError("OpenAI провайдер недоступен")

        return await provider.generate_protocol(
            transcription,
            template_variables,
            diarization_data,
            preset=preset,
            **kwargs,
        )


async def generate_protocol(
    manager: 'LLMManager',
    preset: Dict[str, Any],
    transcription: str,
    template_variables: Dict[str, str],
    diarization_data: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Module-level convenience wrapper used by older call sites."""
    return await manager.generate_protocol(
        preset=preset,
        transcription=transcription,
        template_variables=template_variables,
        diarization_data=diarization_data,
        **kwargs,
    )
