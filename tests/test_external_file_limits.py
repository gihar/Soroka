"""Лимит внешних файлов 2 ГБ и таймауты скачивания (issue #92).

Часовая запись встречи в видео легко превышает старые 50 МБ; общий
5-минутный таймаут сессии обрывал большие честные скачивания.
"""

import pytest

from src.exceptions.file import FileSizeError
from src.services.url_service import URLService

GB = 1024 ** 3


class TestExternalFileSizeLimit:
    def test_default_limit_is_two_gb(self, monkeypatch):
        # Дефолт без влияния локального .env и переменных окружения
        monkeypatch.delenv("MAX_EXTERNAL_FILE_SIZE", raising=False)
        from src.config import Settings

        assert Settings(_env_file=None).max_external_file_size == 2 * GB

    def test_accepts_file_within_limit_and_rejects_over(self, monkeypatch):
        from src.config import settings

        monkeypatch.setattr(settings, "max_external_file_size", 2 * GB)
        service = URLService()

        service.validate_file_by_info("meeting.mp4", int(1.5 * GB))  # не бросает
        with pytest.raises(FileSizeError):
            service.validate_file_by_info("meeting.mp4", int(2.5 * GB))


class TestDownloadSessionTimeouts:
    @pytest.mark.anyio
    async def test_no_total_timeout_but_stalled_reads_cut(self):
        async with URLService() as service:
            timeout = service.session.timeout
            assert timeout.total is None, "общий таймаут обрывает большие скачивания"
            assert timeout.sock_read, "зависшее чтение должно обрываться"
            assert timeout.sock_connect, "зависшее соединение должно обрываться"
