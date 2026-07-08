"""Модель результата валидации протокола."""
from dataclasses import dataclass, field
from typing import List


@dataclass
class ValidationResult:
    """Результат валидации протокола"""
    is_valid: bool
    completeness_score: float  # 0-1
    structure_score: float  # 0-1
    factual_accuracy_score: float  # 0-1
    diarization_usage_score: float  # 0-1
    overall_score: float  # 0-1
    
    missing_fields: List[str] = field(default_factory=list)
    empty_fields: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """Преобразовать в словарь"""
        return {
            "is_valid": self.is_valid,
            "scores": {
                "completeness": self.completeness_score,
                "structure": self.structure_score,
                "factual_accuracy": self.factual_accuracy_score,
                "diarization_usage": self.diarization_usage_score,
                "overall": self.overall_score
            },
            "issues": {
                "missing_fields": self.missing_fields,
                "empty_fields": self.empty_fields
            },
            "warnings": self.warnings,
            "suggestions": self.suggestions
        }

