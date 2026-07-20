"""Мёртвый флоу быстрого фидбэка удалён.

`QuickFeedbackManager.request_quick_feedback` («Как вам протокол?» 👍😐👎)
нигде не вызывался — весь недостижимый путь снят. /feedback остаётся.
"""

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def test_quick_feedback_manager_gone_from_module():
    import src.ux.feedback_system as fs

    assert not hasattr(fs, "QuickFeedbackManager")


def test_quick_feedback_manager_not_exported():
    import src.ux as ux

    assert "QuickFeedbackManager" not in getattr(ux, "__all__", [])
    assert not hasattr(ux, "QuickFeedbackManager")


def test_bot_no_longer_registers_quick_feedback():
    text = (_ROOT / "src" / "bot.py").read_text(encoding="utf-8")
    assert "QuickFeedbackManager" not in text
    assert "quick_feedback" not in text


def test_regular_feedback_flow_intact():
    """`/feedback` жив: FeedbackUI и обработчики оценки на месте."""
    import src.ux.feedback_system as fs

    assert hasattr(fs, "FeedbackUI")
    assert hasattr(fs, "setup_feedback_handlers")
