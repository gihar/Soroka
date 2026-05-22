"""Backward-compatible re-export. Real module lives in src/config.py."""
from src.config import OpenAIModelPreset, Settings, settings

__all__ = ["Settings", "OpenAIModelPreset", "settings"]
