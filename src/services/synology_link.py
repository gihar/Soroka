"""
Резолвер публичных share-ссылок Synology Drive.

У Synology нет фиксированного домена — каждый NAS живёт на своём хосте
(включая *.quickconnect.to), поэтому ссылка распознаётся по пути:
https://<хост>[:порт]/d/s/<токен-ссылки>/<ключ>.

Рецепт скачивания (reverse-engineered, проверен на DSM 7, 2026-07-23):

1. GET https://<хост>/d/s/<ID>/<КЛЮЧ> — сервер ставит cookie
   ``drive-sharing-<КЛЮЧ>``, значение которой и есть sharing_token
   (в веб-приложении Drive это делает GetSharingToken() из
   synodrive_common.js). Все последующие запросы обязаны идти той же
   HTTP-сессией: токен-кука живёт в cookie jar.
2. GET https://<хост>/webapi/entry.cgi?api=SYNO.SynologyDrive.Shard&
   version=1&method=getjs&permanent_link="<ID>"&sharing_type="public_sharing"&
   sharing_link="<КЛЮЧ>" — в ответе среди JS-строк есть
   ``window.getDriveFile=function(){return {...}}`` с JSON файла:
   file_id, name, флаги доступа.
3. GET https://<хост>/d/s/<ID>/webapi/entry.cgi/<имя-файла>?
   api=SYNO.SynologyDrive.Files&method=download&version=2&
   files=["id:<file_id>"]&force_download=true&sharing_token="<токен>" —
   байты файла. HEAD на тот же URL отдаёт content-length и
   content-disposition; Range поддерживается.
"""

import json
import re
from typing import Tuple
from urllib.parse import quote, urlencode, urlsplit

from src.exceptions.file import FileError

_SHARE_URL_RE = re.compile(
    r"https?://[^/\s]+/d/s/(?P<link_id>[A-Za-z0-9]+)/(?P<key>[A-Za-z0-9_.\-]+)"
)

_FILE_OBJECT_MARKER = "getDriveFile=function(){return "


def is_synology_share_url(url: str) -> bool:
    """Похожа ли ссылка на публичную share-ссылку Synology Drive."""
    return _SHARE_URL_RE.search(url) is not None


class SynologyShareResolver:
    """Проходит рецепт скачивания (см. docstring модуля) на общей HTTP-сессии.

    Сессия обязана быть той же, что скачивает файл: токен-кука из шага 1
    живёт в её cookie jar.
    """

    def __init__(self, session):
        self.session = session

    async def get_file_info(self, url: str) -> Tuple[str, int, str]:
        """Вернуть (имя файла, размер, прямая ссылка на скачивание)."""
        match = _SHARE_URL_RE.search(url)
        if not match:
            raise FileError("Ссылка не похожа на share-ссылку Synology Drive")
        link_id, key = match.group("link_id"), match.group("key")
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"

        token = await self._fetch_sharing_token(base, link_id, key)
        file_object = await self._fetch_file_object(base, link_id, key)

        file_id = file_object.get("file_id")
        filename = file_object.get("name")
        if not file_id or not filename:
            raise FileError("Не удалось получить данные файла по ссылке Synology Drive")

        direct_url = self._build_download_url(base, link_id, filename, file_id, token)
        file_size = await self._fetch_size(direct_url)
        return filename, file_size, direct_url

    async def _fetch_sharing_token(self, base: str, link_id: str, key: str) -> str:
        """Шаг 1: страница шаринга ставит куку drive-sharing-<КЛЮЧ> = токен."""
        async with self.session.get(f"{base}/d/s/{link_id}/{key}") as response:
            if response.status != 200:
                raise FileError(
                    f"Ссылка Synology Drive недоступна (код ответа: {response.status})"
                )
            morsel = response.cookies.get(f"drive-sharing-{key}")
            if morsel is None:
                raise FileError("Не удалось получить токен доступа по ссылке Synology Drive")
            return morsel.value

    async def _fetch_file_object(self, base: str, link_id: str, key: str) -> dict:
        """Шаг 2: Shard getjs содержит window.getDriveFile с JSON файла."""
        query = urlencode({
            "api": "SYNO.SynologyDrive.Shard",
            "version": "1",
            "method": "getjs",
            "permanent_link": f'"{link_id}"',
            "sharing_type": '"public_sharing"',
            "sharing_link": f'"{key}"',
        })
        async with self.session.get(f"{base}/webapi/entry.cgi?{query}") as response:
            if response.status != 200:
                raise FileError(
                    f"Не удалось получить данные файла Synology Drive "
                    f"(код ответа: {response.status})"
                )
            body = await response.text()
        marker_at = body.find(_FILE_OBJECT_MARKER)
        if marker_at == -1:
            raise FileError("Не удалось получить данные файла по ссылке Synology Drive")
        start = marker_at + len(_FILE_OBJECT_MARKER)
        try:
            file_object, _ = json.JSONDecoder().raw_decode(body, start)
        except json.JSONDecodeError as e:
            raise FileError(f"Не удалось разобрать данные файла Synology Drive: {e}")
        return file_object

    def _build_download_url(
        self, base: str, link_id: str, filename: str, file_id: str, token: str
    ) -> str:
        """Шаг 3: прямая ссылка на скачивание с sharing_token в запросе."""
        query = urlencode({
            "api": "SYNO.SynologyDrive.Files",
            "method": "download",
            "version": "2",
            "files": f'["id:{file_id}"]',
            "force_download": "true",
            "sharing_token": f'"{token}"',
        })
        return f"{base}/d/s/{link_id}/webapi/entry.cgi/{quote(filename)}?{query}"

    async def _fetch_size(self, direct_url: str) -> int:
        """Размер из content-length; 0, если сервер его не отдал."""
        async with self.session.head(direct_url) as response:
            if response.status != 200:
                raise FileError(
                    f"Файл по ссылке Synology Drive недоступен для скачивания "
                    f"(код ответа: {response.status})"
                )
            content_length = response.headers.get("content-length")
            return int(content_length) if content_length else 0
