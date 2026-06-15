"""FileService must reuse ONE process-wide Bot, not create one per instance.

Regression (aiohttp session leak): a fresh FileService was built per task
(ProcessingService -> BaseProcessingService), each creating its own aiogram Bot
whose underlying aiohttp ClientSession (opened by get_file) was never closed —
one leaked session per processed file. Reusing a single shared Bot means a
single session for the whole process.
"""
import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "src"))


def _patch_bot(monkeypatch):
    import src.services.file_service as fs

    created = []

    def fake_bot(token=None, **kwargs):
        sentinel = object()
        created.append(sentinel)
        return sentinel

    monkeypatch.setattr(fs, "Bot", fake_bot)
    monkeypatch.setattr(fs, "_shared_bot", None, raising=False)
    return fs, created


def test_constructing_file_service_creates_no_bot(monkeypatch):
    """Building a FileService must not open a Bot/session (it's per-task)."""
    fs, created = _patch_bot(monkeypatch)
    fs.FileService()
    fs.FileService()
    assert created == []


def test_shared_bot_is_created_once_and_reused(monkeypatch):
    """The file-lookup Bot is created lazily once and reused process-wide."""
    fs, created = _patch_bot(monkeypatch)
    b1 = fs._get_file_bot()
    b2 = fs._get_file_bot()
    assert b1 is b2
    assert len(created) == 1
