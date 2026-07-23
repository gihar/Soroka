"""Живой интеграционный тест Synology-ссылки против реального NAS (issue #94).

Назначение — ловить дрейф совместимости после обновлений DSM: рецепт
скачивания reverse-engineered, и Synology может его поменять.

Запуск вручную (в CI пропускается — переменная окружения не задана):

    SYNOLOGY_LIVE_SHARE_URL='https://<хост>/d/s/<токен>/<ключ>' \
        venv/bin/python -m pytest -m live_synology tests/test_synology_live.py

Эталонная ссылка задаётся только переменной окружения: публичная ссылка
даёт доступ к файлу, в репозитории ей не место.
"""

import os

import pytest

LIVE_URL = os.environ.get("SYNOLOGY_LIVE_SHARE_URL")

pytestmark = [
    pytest.mark.live_synology,
    pytest.mark.skipif(
        not LIVE_URL,
        reason=(
            "Живой тест пропущен: задайте SYNOLOGY_LIVE_SHARE_URL="
            "'https://<хост>/d/s/<токен>/<ключ>' и запустите "
            "pytest -m live_synology tests/test_synology_live.py"
        ),
    ),
]


@pytest.mark.anyio
async def test_recipe_downloads_real_file_from_nas():
    from src.services.url_service import URLService

    async with URLService() as service:
        assert service.is_supported_url(LIVE_URL)

        filename, file_size, direct_url = await service.get_file_info(LIVE_URL)
        assert filename, "имя файла должно определяться до скачивания"
        assert file_size > 0, "размер должен определяться до скачивания"

        temp_path = await service.download_file(direct_url, filename)

    try:
        actual_size = os.path.getsize(temp_path)
        assert actual_size == file_size

        with open(temp_path, "rb") as f:
            head = f.read(16)
        # Сигнатура MP4-контейнера: 'ftyp' в начале файла
        assert b"ftyp" in head, f"неожиданные первые байты: {head!r}"
    finally:
        os.unlink(temp_path)
