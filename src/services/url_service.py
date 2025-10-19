"""
Сервис для работы с URL файлами (Google Drive, Яндекс.Диск)
"""

import re
import os
import tempfile
import aiohttp
import asyncio
from typing import Tuple, Optional
from urllib.parse import urlparse, parse_qs
from loguru import logger

from config import settings
from src.exceptions.file import FileError, FileSizeError, FileTypeError


class URLService:
    """Сервис для работы с URL файлами"""
    
    # Поддерживаемые расширения файлов
    SUPPORTED_EXTENSIONS = ['.mp3', '.wav', '.m4a', '.ogg', '.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv']
    
    # Паттерны для распознавания ссылок
    GOOGLE_DRIVE_PATTERNS = [
        r'https://drive\.google\.com/file/d/([a-zA-Z0-9_-]+)',
        r'https://drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)',
        r'https://docs\.google\.com/.*/d/([a-zA-Z0-9_-]+)'
    ]
    
    YANDEX_DISK_PATTERNS = [
        r'https://disk\.yandex\.[a-z]{2,3}/i/([a-zA-Z0-9_-]+)',
        r'https://yadi\.sk/i/([a-zA-Z0-9_-]+)',
        r'https://disk\.yandex\.[a-z]{2,3}/d/([a-zA-Z0-9_-]+)'
    ]
    
    def __init__(self):
        self.session = None
    
    async def __aenter__(self):
        """Async context manager entry"""
        import ssl
        
        # Создаем SSL контекст в зависимости от настроек
        ssl_context = None
        if not settings.ssl_verify:
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=300),  # 5 минут таймаут
            headers={'User-Agent': 'Mozilla/5.0 (compatible; SorokaBot/1.0)'}
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()
    
    def is_supported_url(self, url: str) -> bool:
        """Проверить, поддерживается ли данный URL"""
        return self._is_google_drive_url(url) or self._is_yandex_disk_url(url)
    
    def _is_google_drive_url(self, url: str) -> bool:
        """Проверить, является ли URL ссылкой на Google Drive"""
        return any(re.search(pattern, url) for pattern in self.GOOGLE_DRIVE_PATTERNS)
    
    def _is_yandex_disk_url(self, url: str) -> bool:
        """Проверить, является ли URL ссылкой на Яндекс.Диск"""
        return any(re.search(pattern, url) for pattern in self.YANDEX_DISK_PATTERNS)
    
    def _extract_google_drive_id(self, url: str) -> Optional[str]:
        """Извлечь ID файла из ссылки Google Drive"""
        for pattern in self.GOOGLE_DRIVE_PATTERNS:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None
    
    def _get_google_drive_direct_url(self, file_id: str) -> str:
        """Получить прямую ссылку для скачивания с Google Drive"""
        # Добавляем параметр confirm=t для обхода предупреждения о больших файлах
        return f"https://drive.google.com/uc?export=download&id={file_id}&confirm=t"
    
    async def _get_google_drive_real_download_url(self, file_id: str) -> str:
        """Получить реальную ссылку для скачивания с Google Drive, обходя предупреждения"""
        # Сначала пробуем стандартный метод
        initial_url = f"https://drive.google.com/uc?export=download&id={file_id}"
        
        try:
            # Делаем запрос без редиректов, чтобы получить промежуточную ссылку
            async with self.session.get(initial_url, allow_redirects=False) as response:
                if response.status == 303:
                    # Получаем ссылку из Location заголовка
                    location = response.headers.get('location')
                    if location:
                        # Проверяем, ведет ли ссылка на HTML страницу с предупреждением
                        async with self.session.get(location, allow_redirects=False) as warning_response:
                            if warning_response.status == 200:
                                content_type = warning_response.headers.get('content-type', '').lower()
                                if 'text/html' in content_type:
                                    # Это HTML страница с предупреждением, нужно извлечь реальную ссылку
                                    html_content = await warning_response.text()
                                    # Ищем ссылку для скачивания в HTML
                                    import re
                                    download_match = re.search(r'href="([^"]*download[^"]*)"', html_content)
                                    if download_match:
                                        download_url = download_match.group(1)
                                        # Если ссылка относительная, делаем её абсолютной
                                        if download_url.startswith('/'):
                                            download_url = 'https://drive.usercontent.google.com' + download_url
                                        return download_url
                                    else:
                                        # Если не нашли ссылку в HTML, пробуем альтернативный метод
                                        return f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t"
                                else:
                                    # Это не HTML, значит прямая ссылка на файл
                                    return location
                            else:
                                return location
                    else:
                        # Если нет Location заголовка, используем стандартный метод
                        return self._get_google_drive_direct_url(file_id)
                else:
                    # Если не редирект, используем исходную ссылку
                    return initial_url
        except Exception as e:
            logger.warning(f"Ошибка при получении реальной ссылки Google Drive: {e}")
            # В случае ошибки возвращаем стандартную ссылку
            return self._get_google_drive_direct_url(file_id)
    
    async def _get_yandex_disk_direct_url(self, url: str) -> str:
        """Получить прямую ссылку для скачивания с Яндекс.Диска"""
        # Для Яндекс.Диска нужно получить публичную ссылку через API
        # Пытаемся добавить /download к ссылке
        if '/i/' in url:
            return url.replace('/i/', '/d/')
        elif '/d/' not in url:
            # Если это публичная ссылка, добавляем /download
            return url + '/download' if not url.endswith('/') else url + 'download'
        return url
    
    async def get_file_info(self, url: str) -> Tuple[str, int, str]:
        """
        Получить информацию о файле по URL
        Возвращает: (filename, file_size, direct_url)
        """
        if not self.session:
            raise FileError("Сессия не инициализирована")
        
        try:
            if self._is_google_drive_url(url):
                return await self._get_google_drive_file_info(url)
            elif self._is_yandex_disk_url(url):
                return await self._get_yandex_disk_file_info(url)
            else:
                raise FileError("Неподдерживаемый тип ссылки")
        
        except aiohttp.ClientError as e:
            logger.error(f"Ошибка при получении информации о файле: {e}")
            raise FileError(f"Ошибка при получении информации о файле: {e}")
        except Exception as e:
            logger.error(f"Неожиданная ошибка в get_file_info: {e}")
            logger.error(f"Тип исключения в get_file_info: {type(e).__name__}")
            if isinstance(e, FileSizeError):
                logger.error(f"=== FileSizeError ПЕРЕХВАЧЕНА В get_file_info ===")
                logger.error(f"FileSizeError выбрасывается в get_file_info!")
                logger.error(f"Пробрасываем FileSizeError из get_file_info")
            raise
    
    async def _get_google_drive_file_info(self, url: str) -> Tuple[str, int, str]:
        """Получить информацию о файле Google Drive"""
        file_id = self._extract_google_drive_id(url)
        if not file_id:
            raise FileError("Не удалось извлечь ID файла из ссылки Google Drive")
        
        # Пытаемся получить прямую ссылку через альтернативный метод
        direct_url = await self._get_google_drive_real_download_url(file_id)
        
        # Выполняем HEAD запрос для получения информации о файле
        async with self.session.head(direct_url, allow_redirects=True) as response:
            if response.status == 200:
                # Получаем размер файла
                content_length = response.headers.get('content-length')
                if content_length:
                    file_size = int(content_length)
                    logger.info(f"Размер файла получен из content-length: {file_size}")
                else:
                    # Если размер неизвестен, делаем частичный GET запрос
                    file_size = await self._get_file_size_by_range(direct_url)
                    logger.info(f"Размер файла получен из range запроса: {file_size}")
                
                # Получаем имя файла
                content_disposition = response.headers.get('content-disposition', '')
                filename = self._extract_filename_from_header(content_disposition)
                
                if not filename:
                    # Пытаемся получить имя из URL или используем ID с расширением
                    # Определяем расширение по Content-Type или используем mp4 по умолчанию
                    content_type = response.headers.get('content-type', '').lower()
                    if 'audio' in content_type:
                        if 'mp3' in content_type:
                            ext = '.mp3'
                        elif 'wav' in content_type:
                            ext = '.wav'
                        elif 'ogg' in content_type:
                            ext = '.ogg'
                        else:
                            ext = '.mp3'  # По умолчанию для аудио
                    elif 'video' in content_type:
                        if 'mp4' in content_type:
                            ext = '.mp4'
                        elif 'avi' in content_type:
                            ext = '.avi'
                        else:
                            ext = '.mp4'  # По умолчанию для видео
                    else:
                        ext = '.mp4'  # По умолчанию
                    
                    filename = f"gdrive_file_{file_id}{ext}"
                
                return filename, file_size, direct_url
            else:
                raise FileError(f"Не удалось получить доступ к файлу. Код ответа: {response.status}")
    
    async def _get_yandex_disk_file_info(self, url: str) -> Tuple[str, int, str]:
        """Получить информацию о файле Яндекс.Диска"""
        direct_url = await self._get_yandex_disk_direct_url(url)
        
        # Выполняем HEAD запрос для получения информации о файле
        async with self.session.head(direct_url, allow_redirects=True) as response:
            if response.status == 200:
                # Получаем размер файла
                content_length = response.headers.get('content-length')
                if content_length:
                    file_size = int(content_length)
                else:
                    file_size = await self._get_file_size_by_range(direct_url)
                
                # Получаем имя файла
                content_disposition = response.headers.get('content-disposition', '')
                filename = self._extract_filename_from_header(content_disposition)
                
                if not filename:
                    # Извлекаем из URL или генерируем с расширением
                    parsed_url = urlparse(direct_url)
                    filename = os.path.basename(parsed_url.path)
                    
                    if not filename or '.' not in filename:
                        # Определяем расширение по Content-Type
                        content_type = response.headers.get('content-type', '').lower()
                        if 'audio' in content_type:
                            if 'mp3' in content_type:
                                ext = '.mp3'
                            elif 'wav' in content_type:
                                ext = '.wav'
                            elif 'ogg' in content_type:
                                ext = '.ogg'
                            else:
                                ext = '.mp3'  # По умолчанию для аудио
                        elif 'video' in content_type:
                            if 'mp4' in content_type:
                                ext = '.mp4'
                            elif 'avi' in content_type:
                                ext = '.avi'
                            else:
                                ext = '.mp4'  # По умолчанию для видео
                        else:
                            ext = '.mp4'  # По умолчанию
                        
                        filename = f"yandex_disk_file{ext}"
                
                return filename, file_size, direct_url
            else:
                raise FileError(f"Не удалось получить доступ к файлу. Код ответа: {response.status}")
    
    async def _get_file_size_by_range(self, url: str) -> int:
        """Получить размер файла через Range запрос"""
        headers = {'Range': 'bytes=0-0'}
        async with self.session.get(url, headers=headers) as response:
            if response.status == 206:  # Partial Content
                content_range = response.headers.get('content-range', '')
                if content_range:
                    # Формат: "bytes 0-0/total_size"
                    total_size = content_range.split('/')[-1]
                    if total_size.isdigit():
                        return int(total_size)
            
            # Если не удалось получить размер, возвращаем 0
            logger.warning(f"Не удалось определить размер файла для {url}")
            return 0
    
    def _extract_filename_from_header(self, content_disposition: str) -> Optional[str]:
        """Извлечь имя файла из заголовка Content-Disposition"""
        if not content_disposition:
            return None
        
        # Ищем filename="..." или filename*=UTF-8''...
        filename_match = re.search(r'filename[*]?=["\']?([^"\';\n]+)', content_disposition)
        if filename_match:
            filename = filename_match.group(1).strip()
            # Убираем UTF-8'' префикс если есть
            if filename.startswith("UTF-8''"):
                filename = filename[7:]
            return filename
        
        return None
    
    def validate_file_by_info(self, filename: str, file_size: int) -> None:
        """Валидация файла по его информации"""
        # Проверка размера
        if file_size > settings.max_external_file_size:
            logger.error(f"=== FileSizeError ВЫБРАСЫВАЕТСЯ В validate_file_by_info ===")
            logger.error(f"Размер файла: {file_size}, лимит: {settings.max_external_file_size}")
            error = FileSizeError(
                file_size,
                settings.max_external_file_size,
                filename
            )
            logger.error(f"FileSizeError создан: {error}")
            raise error
        
        # Проверка расширения
        if filename:
            file_ext = os.path.splitext(filename.lower())[1]
            if file_ext and file_ext not in self.SUPPORTED_EXTENSIONS:
                raise FileTypeError(
                    file_ext,
                    self.SUPPORTED_EXTENSIONS,
                    filename
                )
    
    async def download_file(self, url: str, filename: str) -> str:
        """
        Скачать файл и сохранить во временную директорию
        Возвращает путь к скачанному файлу
        """
        if not self.session:
            raise FileError("Сессия не инициализирована")
        
        # Создаем временный файл с правильным расширением
        os.makedirs(settings.temp_dir, exist_ok=True)
        
        # Определяем расширение файла
        file_ext = os.path.splitext(filename)[1] if filename else ''
        if not file_ext:
            # Если расширения нет, пытаемся определить по URL или используем .mp4 по умолчанию
            if any(fmt in url.lower() for fmt in ['.mp3', '.wav', '.m4a', '.ogg']):
                file_ext = '.mp3'  # По умолчанию для аудио
            else:
                file_ext = '.mp4'  # По умолчанию для видео
        
        temp_file = tempfile.NamedTemporaryFile(
            dir=settings.temp_dir,
            suffix=file_ext,
            delete=False
        )
        temp_path = temp_file.name
        temp_file.close()
        
        try:
            # Получаем прямую ссылку
            if self._is_google_drive_url(url):
                file_id = self._extract_google_drive_id(url)
                download_url = await self._get_google_drive_real_download_url(file_id)
            elif self._is_yandex_disk_url(url):
                download_url = await self._get_yandex_disk_direct_url(url)
            else:
                download_url = url
            
            # Скачиваем файл
            async with self.session.get(download_url) as response:
                if response.status == 200:
                    with open(temp_path, 'wb') as f:
                        async for chunk in response.content.iter_chunked(8192):
                            f.write(chunk)
                    
                    logger.info(f"Файл успешно скачан: {temp_path}")
                    return temp_path
                else:
                    raise FileError(f"Ошибка при скачивании файла. Код ответа: {response.status}")
        
        except Exception as e:
            # Удаляем временный файл в случае ошибки
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise FileError(f"Ошибка при скачивании файла: {e}")
    
    async def process_url(self, url: str) -> Tuple[str, str]:
        """
        Полная обработка URL: проверка, валидация и скачивание
        Возвращает: (temp_file_path, original_filename)
        """
        # Проверяем поддержку URL
        if not self.is_supported_url(url):
            raise FileError("Неподдерживаемый тип ссылки. Поддерживаются только Google Drive и Яндекс.Диск")
        
        # Получаем информацию о файле
        filename, file_size, direct_url = await self.get_file_info(url)
        
        # Валидация файла должна быть выполнена вызывающим кодом
        # self.validate_file_by_info(filename, file_size)
        
        # Скачиваем файл
        temp_path = await self.download_file(url, filename)
        
        return temp_path, filename
