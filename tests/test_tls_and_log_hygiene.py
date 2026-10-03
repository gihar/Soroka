"""TLS-проверка включена по умолчанию, а флаг её отключения не трогает процесс
целиком; трейсбэки в логах не раскрывают значения переменных.

Аудит прода 2026-09-22: с SSL_VERIFY=false main.py подменял SSL-контекст по
умолчанию для всего процесса, а speechmatics_service — ещё и httpx.Client,
так что без проверки сертификатов ходили и Telegram, и OpenRouter. Loguru с
diagnose=True печатал в трейсбэках локальные переменные — имена и фамилии
пользователей из CallbackQuery оседали в journald и logs/bot.log.
"""

import importlib
import re
import ssl
import sys

import httpx
import pytest
from loguru import logger


class TestTlsVerification:
    def test_verification_enabled_by_default(self, monkeypatch):
        monkeypatch.delenv("SSL_VERIFY", raising=False)
        from src.config import Settings

        assert Settings(_env_file=None).ssl_verify is True

    def test_disabled_flag_does_not_patch_process_ssl_default(self, monkeypatch):
        from src.config import settings

        original = ssl._create_default_https_context
        # Откатит подмену, даже если тест упадёт
        monkeypatch.setattr(ssl, "_create_default_https_context", original)
        monkeypatch.setattr(settings, "ssl_verify", False)

        import main

        importlib.reload(main)

        assert ssl._create_default_https_context is original

    def test_speechmatics_gets_own_context_without_patching_httpx(self, monkeypatch):
        from src.config import settings
        from src.services import speechmatics_service

        if not speechmatics_service.SPEECHMATICS_AVAILABLE:
            pytest.skip("Speechmatics SDK не установлен")

        original_https = ssl._create_default_https_context
        original_init = httpx.Client.__init__
        monkeypatch.setattr(ssl, "_create_default_https_context", original_https)
        monkeypatch.setattr(httpx.Client, "__init__", original_init)
        monkeypatch.setattr(settings, "ssl_verify", False)
        monkeypatch.setattr(settings, "speechmatics_api_key", "test-key")

        module = importlib.reload(speechmatics_service)
        service = module.SpeechmaticsService()

        assert service.settings.ssl_context.verify_mode == ssl.CERT_NONE
        assert httpx.Client.__init__ is original_init
        assert ssl._create_default_https_context is original_https

    def test_speechmatics_verifies_when_enabled(self, monkeypatch):
        from src.config import settings
        from src.services import speechmatics_service

        if not speechmatics_service.SPEECHMATICS_AVAILABLE:
            pytest.skip("Speechmatics SDK не установлен")

        monkeypatch.setattr(settings, "ssl_verify", True)
        monkeypatch.setattr(settings, "speechmatics_api_key", "test-key")

        service = speechmatics_service.SpeechmaticsService()

        assert service.settings.ssl_context.verify_mode == ssl.CERT_REQUIRED
        assert service.settings.ssl_context.check_hostname is True


class TestTracebackHygiene:
    @pytest.fixture
    def configured_logging(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from src.utils.logging_utils import setup_logging

        setup_logging()
        yield tmp_path / "logs" / "bot.log"
        logger.remove()
        logger.add(sys.stderr)

    def test_traceback_does_not_reveal_local_values(self, configured_logging, capsys):
        def handler():
            user_full_name = "Natalya Petrova"  # noqa: F841 — как в CallbackQuery
            raise RuntimeError("boom")

        try:
            handler()
        except RuntimeError:
            logger.exception("Ошибка в обработчике")

        console = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)
        file_log = configured_logging.read_text(encoding="utf-8")

        for output in (console, file_log):
            assert "RuntimeError: boom" in output, "трейсбэк должен остаться"
            assert "Natalya Petrova" not in output
            assert "└" not in output, "аннотации переменных loguru diagnose"
