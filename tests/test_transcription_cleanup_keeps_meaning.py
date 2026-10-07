"""Очистка транскрипции не трогает смысл (#129).

Модель видит очищенный текст, когда диаризации нет, и при перегенерации старых
записей истории — искажения очистки уходят прямо в протокол. Очистка убирает
только междометия без смысла; смысловые слова, правильные фразы, технические
токены и абзацы остаются как были.
"""

import pytest

from src.services.transcription_preprocessor import TranscriptionPreprocessor


def _clean(text: str) -> str:
    return TranscriptionPreprocessor("ru").preprocess(text)["cleaned_text"]


@pytest.mark.parametrize("phrase", [
    "это значит, что срок сдвигается",
    "допустим, 500 тысяч",
    "предположим, что поставщик откажет",
    "в принципе, мы готовы",
    "нужен типа отчёт по продажам",
    "это как бы временное решение",
    "короче, переносим релиз",
    "чисто технически это возможно",
])
def test_meaningful_words_survive(phrase):
    assert _clean(phrase) == phrase


@pytest.mark.parametrize("phrase", [
    "по этому вопросу решили позже",
    "и так далее",
    "что бы ты хотел обсудить",
    "так же, как в прошлый раз",
])
def test_correct_phrases_are_not_rewritten(phrase):
    assert _clean(phrase) == phrase


@pytest.mark.parametrize("token", ["file.py", "v2.1", "http://x.ru", "10:30"])
def test_technical_tokens_stay_whole(token):
    assert token in _clean(f"смотри {token} сегодня")


def test_line_breaks_survive():
    assert _clean("первая реплика\n\nвторая реплика") == "первая реплика\n\nвторая реплика"


def test_bare_interjections_are_removed():
    assert _clean("ээ мы э-э запускаем мм релиз") == "мы запускаем релиз"


def test_speaker_turn_grouping_is_gone():
    """Группировка искала «Спикер N», а метки — SPEAKER_N: метод был мёртв."""
    assert not hasattr(TranscriptionPreprocessor, "group_speaker_turns")
