"""LLM providers package."""
from .base import LLMProvider
from .json_utils import safe_json_parse
from .manager import LLMManager, generate_protocol

# Global singleton (matches original llm_providers.py behavior)
llm_manager = LLMManager()

__all__ = [
    "LLMProvider", "LLMManager",
    "llm_manager", "safe_json_parse", "generate_protocol",
]
