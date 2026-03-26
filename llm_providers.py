"""Backward-compatible re-export. Real module lives in src/llm/."""
from src.llm import llm_manager, safe_json_parse, generate_protocol, LLMProvider, LLMManager
from src.llm.prompt_builders import _build_system_prompt, _build_user_prompt

__all__ = [
    "llm_manager", "safe_json_parse", "generate_protocol",
    "LLMProvider", "LLMManager",
    "_build_system_prompt", "_build_user_prompt",
]
