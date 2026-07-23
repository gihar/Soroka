"""Тесты резолвера публичных share-ссылок Synology Drive (issue #91)."""

from http.cookies import SimpleCookie

import pytest

from src.services.synology_link import SynologyShareResolver, is_synology_share_url

SHARE_URL = (
    "https://nas.example.ru:5001/d/s/11UHOawuDdibJm72X4Pt7PZladIih1sP/"
    "w7a_rScfirhnkpgMsBSIrAEflbg6Yk8j-RrLAz38hXw0"
)
SHARE_KEY = "w7a_rScfirhnkpgMsBSIrAEflbg6Yk8j-RrLAz38hXw0"
TOKEN = "FakeToken123.abc_def"
FILE_ID = "859447920087318451"
FILENAME = "video1127291797.mp4"
FILE_SIZE = 35853577

SHARD_BODY = (
    'window.getDriveShareMode=function(){return \'public\';}\n'
    'window.getDriveFile=function(){return {"file_id":"' + FILE_ID + '",'
    '"name":"' + FILENAME + '","content_type":"video","type":"file",'
    '"adv_shared_info":{"has_password":false},"disable_download":false,'
    '"capabilities":{"can_download":true}}};\n'
    'window.getDriveTexts=function(){return {"action":{"download":"Скачать"}};}'
)


class FakeResponse:
    def __init__(self, status=200, headers=None, body="", cookies=None):
        self.status = status
        self.headers = headers or {}
        self._body = body
        self.cookies = SimpleCookie()
        for name, value in (cookies or {}).items():
            self.cookies[name] = value

    async def text(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Мини-сессия: маршрутизирует запросы по подстроке URL."""

    def __init__(self, routes):
        self.routes = routes  # список (метод, подстрока, FakeResponse)
        self.requests = []  # журнал (метод, url)

    def _match(self, method, url):
        self.requests.append((method, url))
        for m, needle, resp in self.routes:
            if m == method and needle in url:
                return resp
        raise AssertionError(f"Неожиданный запрос: {method} {url}")

    def get(self, url, **kwargs):
        return self._match("GET", url)

    def head(self, url, **kwargs):
        return self._match("HEAD", url)


def make_happy_session():
    return FakeSession(routes=[
        ("GET", "api=SYNO.SynologyDrive.Shard", FakeResponse(body=SHARD_BODY)),
        ("GET", SHARE_KEY, FakeResponse(
            body="<html>...</html>",
            cookies={f"drive-sharing-{SHARE_KEY}": TOKEN},
        )),
        ("HEAD", "method=download", FakeResponse(headers={
            "content-length": str(FILE_SIZE),
            "content-disposition": f'attachment; filename="{FILENAME}"',
        })),
    ])


class TestSynologyShareResolver:
    """Резолвер проходит рецепт: страница → токен, Shard → file_id, HEAD → инфо."""

    @pytest.mark.anyio
    async def test_happy_path_returns_filename_and_size(self):
        resolver = SynologyShareResolver(make_happy_session())

        filename, file_size, direct_url = await resolver.get_file_info(SHARE_URL)

        assert filename == FILENAME
        assert file_size == FILE_SIZE

    @pytest.mark.anyio
    async def test_direct_url_carries_token_file_id_and_download_method(self):
        resolver = SynologyShareResolver(make_happy_session())

        _, _, direct_url = await resolver.get_file_info(SHARE_URL)

        assert direct_url.startswith(
            "https://nas.example.ru:5001/d/s/11UHOawuDdibJm72X4Pt7PZladIih1sP/webapi/entry.cgi/"
        )
        assert "method=download" in direct_url
        assert "id%3A" + FILE_ID in direct_url
        assert f"sharing_token=%22{TOKEN}%22" in direct_url

class TestURLServiceSynologyDelegation:
    """URLService принимает Synology-ссылку как третий тип внешней ссылки."""

    def test_is_supported_url_accepts_synology_share_link(self):
        from src.services.url_service import URLService

        assert URLService().is_supported_url(SHARE_URL)

    @pytest.mark.anyio
    async def test_get_file_info_delegates_to_resolver(self):
        from src.services.url_service import URLService

        service = URLService()
        service.session = make_happy_session()

        filename, file_size, direct_url = await service.get_file_info(SHARE_URL)

        assert filename == FILENAME
        assert file_size == FILE_SIZE
        assert "method=download" in direct_url


class TestSupportedServicesCopy:
    """Тексты бота называют Synology Drive среди поддерживаемых сервисов."""

    def test_help_mentions_synology(self):
        from src.ux.message_builder import MessageBuilder

        assert "Synology" in MessageBuilder.help_message()


class TestSynologyResolverErrors:
    @pytest.mark.anyio
    async def test_page_without_token_cookie_raises_clear_error(self):
        from src.exceptions.file import FileError

        session = FakeSession(routes=[
            ("GET", SHARE_KEY, FakeResponse(body="<html>...</html>", cookies={})),
        ])
        resolver = SynologyShareResolver(session)

        with pytest.raises(FileError, match="токен"):
            await resolver.get_file_info(SHARE_URL)


class TestIsSynologyShareUrl:
    """Распознавание share-ссылки по пути /d/s/ на любом хосте."""

    def test_recognizes_share_link_on_custom_host_with_port(self):
        assert is_synology_share_url(
            "https://nas.example.ru:5001/d/s/11UHOawuDdibJm72X4Pt7PZladIih1sP/"
            "w7a_rScfirhnkpgMsBSIrAEflbg6Yk8j-RrLAz38hXw0"
        )

    def test_recognizes_share_link_without_port(self):
        assert is_synology_share_url("https://drive.company.com/d/s/AbCdEf123/secretKey42")

    def test_recognizes_quickconnect_host(self):
        assert is_synology_share_url("https://example.quickconnect.to/d/s/AbCdEf123/secretKey42")

    def test_rejects_google_drive(self):
        assert not is_synology_share_url("https://drive.google.com/file/d/s0meFileId/view")

    def test_rejects_yandex_disk(self):
        assert not is_synology_share_url("https://disk.yandex.ru/i/AbCdEf123")

    def test_rejects_random_url(self):
        assert not is_synology_share_url("https://example.com/files/report.mp4")

    def test_rejects_share_link_without_key_part(self):
        # Без второго сегмента (ключа) скачивание невозможно — не наша ссылка
        assert not is_synology_share_url("https://nas.example.ru/d/s/AbCdEf123")
