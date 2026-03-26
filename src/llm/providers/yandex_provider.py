"""Yandex GPT provider."""
import httpx
from typing import Dict, Any, Optional
from loguru import logger

from src.config import settings
from src.llm.base import LLMProvider
from src.llm.json_utils import safe_json_parse
from src.llm.prompt_builders import _build_system_prompt, _build_user_prompt


class YandexGPTProvider(LLMProvider):
    """Provider for Yandex GPT."""

    def __init__(self):
        self.api_key = settings.yandex_api_key
        self.folder_id = settings.yandex_folder_id

    def is_available(self) -> bool:
        return self.api_key is not None and self.folder_id is not None

    async def generate_protocol(self, transcription: str, template_variables: Dict[str, str],
                                diarization_data: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """Generate protocol using Yandex GPT."""
        if not self.is_available():
            raise ValueError("Yandex GPT API не настроен")

        speaker_mapping = kwargs.get('speaker_mapping')
        meeting_topic = kwargs.get('meeting_topic')
        meeting_date = kwargs.get('meeting_date')
        meeting_time = kwargs.get('meeting_time')
        participants = kwargs.get('participants')
        meeting_agenda = kwargs.get('meeting_agenda')
        project_list = kwargs.get('project_list')

        system_prompt = _build_system_prompt()

        prompt = _build_user_prompt(
            transcription,
            template_variables,
            diarization_data,
            speaker_mapping,
            meeting_topic,
            meeting_date,
            meeting_time,
            participants,
            meeting_agenda,
            project_list
        )

        headers = {
            "Authorization": f"Api-Key {self.api_key}",
            "Content-Type": "application/json"
        }

        if settings.http_referer:
            headers["Referer"] = settings.http_referer
        if settings.x_title:
            headers["X-Title"] = settings.x_title

        data = {
            "modelUri": f"gpt://{self.folder_id}/yandexgpt-lite",
            "completionOptions": {
                "stream": False,
                "temperature": 0.1,
                "maxTokens": 2000
            },
            "messages": [
                {
                    "role": "system",
                    "text": system_prompt
                },
                {
                    "role": "user",
                    "text": prompt
                }
            ]
        }

        try:
            async with httpx.AsyncClient(verify=settings.ssl_verify) as client:
                response = await client.post(
                    "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
                    headers=headers,
                    json=data,
                    timeout=settings.llm_timeout_seconds
                )
                response.raise_for_status()

                result = response.json()
                content = result["result"]["alternatives"][0]["message"]["text"]
                logger.info(f"Получен ответ от Yandex GPT (длина: {len(content) if content else 0}): {content[:200] if content else 'None'}...")

                return safe_json_parse(content, context="Yandex GPT API response")

        except Exception as e:
            logger.error(f"Ошибка при работе с Yandex GPT API: {e}")
            raise
