"""Abstract base class for LLM providers."""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class LLMProvider(ABC):
    """Base class for all LLM providers."""

    @abstractmethod
    async def generate_protocol(self, transcription: str, template_variables: Dict[str, str],
                                diarization_data: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """Generate protocol from transcription."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if provider is available."""
        pass
