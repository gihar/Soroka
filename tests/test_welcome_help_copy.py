"""Welcome и /help: нейтральный тон, без эмодзи-шума, правда о флоу.

Анти-референсы PRODUCT.md: эмодзи-перегруз, «живенький» тон, устаревшие
описания флоу (обязательный шаг «Выберите ИИ» удалён из продукта).
"""

import re

from src.ux.message_builder import MessageBuilder

_EMOJI_RE = re.compile(r"[←-⯿\U0001F000-\U0001FAFF]")


def _emoji_count(text: str) -> int:
    return len(_EMOJI_RE.findall(text))


# ---------------------------------------------------------------------------
# Welcome: коротко, тихо, с командами
# ---------------------------------------------------------------------------

def test_welcome_is_short_and_quiet():
    text = MessageBuilder.welcome_message()
    assert len(text.splitlines()) <= 8
    assert _emoji_count(text) == 0


def test_welcome_names_core_commands():
    text = MessageBuilder.welcome_message()
    for command in ("/templates", "/settings", "/help"):
        assert command in text


def test_welcome_says_what_bot_does():
    text = MessageBuilder.welcome_message()
    assert "протокол" in text.lower()
    assert "ссылк" in text.lower()  # ссылка — равноправная точка входа


# ---------------------------------------------------------------------------
# /help: правда о текущем флоу, без эмодзи-шума
# ---------------------------------------------------------------------------

def test_help_has_no_removed_mandatory_llm_step():
    text = MessageBuilder.help_message()
    assert "Выберите ИИ" not in text
    assert "автовыбор" not in text.lower()


def test_help_describes_real_menu_flow():
    text = MessageBuilder.help_message()
    assert "Быстрая обработка" in text
    assert "Настроить" in text


def test_help_keeps_formats_and_limits():
    text = MessageBuilder.help_message()
    assert "MP3" in text and "MP4" in text
    assert "20" in text  # лимит размера
    assert "60" in text  # рекомендуемая длительность


def test_help_is_quiet():
    text = MessageBuilder.help_message()
    assert _emoji_count(text) <= 2
    assert "универсальный, деловой" not in text  # несуществующие имена шаблонов
