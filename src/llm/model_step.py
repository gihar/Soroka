"""Единая точка разрешения шага работы с моделью (#112, ADR-0007).

Три вызова модели — сопоставление спикеров, ЭТАП 1 анализа, ЭТАП 2 генерации —
решают один и тот же вопрос: каким клиентом, какой моделью, с каким телом и
какими заголовками идти. Ответ живёт здесь и больше нигде: вызывающий называет
шаг и пресет модели, а получает готовый маршрут.

Пресет — полный адрес провайдера (ADR-0007): он обслуживает все три шага, и
клиент, модель, тело и заголовки шаг получает от него одного. Дешёвым шагам
внутри пресета можно назначить свои модели; пустое поле значит основную модель
пресета. Глобальные настройки остаются точкой правды только там, где пресета не
передали: имя модели бессмысленно вне своего провайдера.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Optional

from src.config import settings


class ModelStep(str, Enum):
    """Шаг работы с моделью — единица маршрутизации.

    Значения совпадают с историческими именами шагов: они уходят в лог, в
    контекст разбора ответа и в метрики кеша токенов.
    """

    SPEAKER_MAPPING = "SpeakerMapping"
    ANALYSIS = "Analysis"
    GENERATION = "Generation"


@dataclass(frozen=True)
class StepRoute:
    """Маршрут шага: всё, что нужно вызову, плюс то, чем шаг обслужен."""

    step: ModelStep
    client: Any
    model: str
    preset_key: Optional[str]
    base_url: Optional[str]
    extra_body: Dict[str, Any]
    extra_headers: Dict[str, str]

    def describe(self) -> str:
        """Строка для лога: какой пресет, модель и адрес обслужили шаг."""
        return (
            f"LLM-шаг {self.step.value}: пресет {self.preset_key or 'глобальный'}, "
            f"модель {self.model}, адрес {self.base_url or 'по умолчанию'}"
        )


# Фабрика клиента по пресету (None — глобальный клиент).
ClientFactory = Callable[[Optional[Dict[str, Any]]], Any]

Preset = Optional[Dict[str, Any]]


# Поле пресета с моделью дешёвого шага; пустое значит «основная модель пресета».
_CHEAP_MODEL_FIELD = {
    ModelStep.SPEAKER_MAPPING: "mapping_model",
    ModelStep.ANALYSIS: "analysis_model",
}


def _model_for(step: ModelStep, preset: Preset) -> str:
    """Имя модели шага; пустое значение откатывается на основную модель.

    Пресет обслуживает шаг → имя берётся у пресета: своё для дешёвого шага, а
    при пустом поле — основная модель пресета (ADR-0007). Глобальные настройки
    моделей дешёвых шагов остаются точкой правды только там, где пресета нет:
    имя модели бессмысленно вне своего провайдера.
    """
    if preset:
        cheap_field = _CHEAP_MODEL_FIELD.get(step)
        cheap_model = preset.get(cheap_field) if cheap_field else None
        return cheap_model or preset.get("model") or settings.openai_model
    if step is ModelStep.SPEAKER_MAPPING:
        return settings.speaker_mapping_model or settings.openai_model
    if step is ModelStep.ANALYSIS:
        return settings.analysis_stage_model or settings.openai_model
    return settings.openai_model


def _provider_params(preset: Preset, field: str) -> Dict[str, Any]:
    """Параметры провайдера из пресета — как есть, копией.

    Единственный источник (ADR-0007): атрибуция OpenRouter и выключение режима
    рассуждения Qwen объявлены в своих пресетах, а не глобально. Шаг, идущий без
    пресета, посторонних параметров не несёт.
    """
    params = (preset or {}).get(field) or {}
    return dict(params)


def resolve_step(step: ModelStep, preset: Preset, client_for: ClientFactory) -> StepRoute:
    """Разрешить «шаг + пресет» в клиента, модель, тело и заголовки вызова."""
    return StepRoute(
        step=step,
        client=client_for(preset),
        model=_model_for(step, preset),
        preset_key=(preset or {}).get("key"),
        base_url=(preset or {}).get("base_url") or settings.openai_base_url,
        extra_body=_provider_params(preset, "extra_body"),
        extra_headers=_provider_params(preset, "extra_headers"),
    )
