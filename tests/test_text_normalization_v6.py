"""Критика v6: детерминированная нормализация дефисов в финальном проходе.

Живой протокол 358 показал «15‑минутки» с неразрывным дефисом (U+2011)
вперемешку с обычным — визуальный разнобой без смысловой нагрузки. Дефис
неразрывный и обычный читаются одинаково, но соседство в одном тексте выдаёт
машину. Длинное тире (U+2014) — легитимный разделитель «задача — ответственный»
и НЕ трогается.
"""

from src.utils.text_processing import normalize_hyphens

_NB_HYPHEN = "‑"  # NON-BREAKING HYPHEN
_EM_DASH = "—"  # длинное тире — структурный разделитель
_EN_DASH = "–"  # среднее тире — диапазон


def test_non_breaking_hyphen_becomes_plain():
    assert normalize_hyphens(f"15{_NB_HYPHEN}минутки") == "15-минутки"


def test_mixed_hyphens_unified():
    text = f"15{_NB_HYPHEN}минутки и 30-минутки"
    assert normalize_hyphens(text) == "15-минутки и 30-минутки"


def test_em_dash_left_untouched():
    text = f"Подготовить отчёт {_EM_DASH} Отв.: Илья"
    assert normalize_hyphens(text) == text


def test_en_dash_left_untouched():
    text = f"с 14:00{_EN_DASH}15:30"
    assert normalize_hyphens(text) == text


def test_plain_hyphen_untouched():
    assert normalize_hyphens("15-минутки") == "15-минутки"


def test_clean_text_untouched():
    text = "Обычный текст без спецсимволов."
    assert normalize_hyphens(text) == text


def test_pipeline_normalizes_hyphens():
    """Единый хвост (ADR-0003) прогоняет нормализацию дефисов — тот же шов,
    что и причёсывание меток спикеров, покрывает все пути генерации."""
    import inspect

    import src.services.processing.completion as completion

    assert "normalize_hyphens" in inspect.getsource(completion)
