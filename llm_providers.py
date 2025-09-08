"""
Модуль для интеграции с различными LLM провайдерами
"""

import json
import asyncio
import httpx
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Tuple
from loguru import logger
from config import settings

import openai
from anthropic import Anthropic


class LLMProvider(ABC):
    """Абстрактный базовый класс для LLM провайдеров"""
    
    @abstractmethod
    async def generate_protocol(self, transcription: str, template_variables: Dict[str, str], diarization_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Генерировать протокол на основе транскрипции и шаблона"""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Проверить доступность провайдера"""
        pass


# -------------------------------------------------------------
# Унифицированные билдеры промптов для всех провайдеров
# -------------------------------------------------------------
def _build_system_prompt() -> str:
    """Строгая системная политика для получения профессионального протокола."""
    return (
        "Ты — профессиональный протоколист. Действуешь как строгий экстрактор фактов из "
        "стенограммы встречи. Не придумывай и не интерпретируй. Если факт отсутствует "
        "или неочевиден — используй \"Не указано\". Пиши кратко и официально-деловым стилем. "
        "Сохраняй термины и формулировки из стенограммы, допускается только лёгкая нормализация. "
        "Отвечай строго валидным JSON-объектом без комментариев, без пояснений и без обрамления."
    )


def _build_user_prompt(
    transcription: str,
    template_variables: Dict[str, str],
    diarization_data: Optional[Dict[str, Any]] = None,
) -> str:
    """Формирует пользовательский промпт с контекстом и требованиями к формату."""
    # Блок контекста (с учётом диаризации)
    if diarization_data and diarization_data.get("formatted_transcript"):
        transcription_text = (
            "Транскрипция с разделением говорящих:\n"
            f"{diarization_data['formatted_transcript']}\n\n"
            "Дополнительная информация:\n"
            f"- Количество говорящих: {diarization_data.get('total_speakers', 'неизвестно')}\n"
            f"- Список говорящих: {', '.join(diarization_data.get('speakers', []))}\n\n"
            "Исходная транскрипция (для справки):\n"
            f"{transcription}\n"
        )
    else:
        transcription_text = (
            "Транскрипция:\n"
            f"{transcription}\n\n"
            "Примечание: Диаризация (разделение говорящих) недоступна для этой записи.\n"
        )

    variables_str = "\n".join([f"- {key}: {desc}" for key, desc in template_variables.items()])

    # Основной пользовательский промпт
    user_prompt = (
        "Контекст для извлечения:\n"
        f"{transcription_text}\n"
        "Переменные для извлечения (ключ: описание):\n"
        f"{variables_str}\n\n"
        "Требования к формату:\n"
        "- Верни только валидный JSON-объект.\n"
        "- Используй строго эти ключи; дополнительные не добавляй.\n"
        "- Сохраняй порядок ключей как в списке переменных.\n"
        "- Значение каждого ключа — строка (UTF-8), без вложенных JSON и без Markdown.\n"
        "- Для перечислений — один пункт на строку, начинай с '- ' (дефис и пробел), без нумерации, без завершающей точки.\n"
        "- Сохраняй факты и формулировки из транскрипции; не добавляй роли, даты, суммы, сроки, если они явно не упомянуты.\n"
        "- Убирай дубликаты, объединяй совпадающие пункты; порядок — по порядку упоминания в тексте.\n"
        "- Если данные отсутствуют или неоднозначны — 'Не указано'.\n\n"
        "Пример корректного ответа:\n"
        "{\n"
        "  \"participants\": \"Иван Иванов; Мария Петрова\",\n"
        "  \"decisions\": \"- Увеличить бюджет на маркетинг\\n- Утвердить новую стратегию\",\n"
        "  \"action_items\": \"- Подготовить презентацию — Ответственный: Мария Петрова\\n- Согласовать бюджет — Ответственный: Иван Иванов\"\n"
        "}\n\n"
        "Недопустимо:\n"
        "- Любой текст вне JSON\n"
        "- Вложенный JSON в значениях\n"
        "- Придуманные роли/сроки/суммы, если их нет в тексте\n"
    )
    return user_prompt


class OpenAIProvider(LLMProvider):
    """Провайдер для OpenAI GPT"""
    
    def __init__(self):
        self.client = None
        if settings.openai_api_key:
            openai.api_key = settings.openai_api_key
            # Создаем HTTP клиент с настройками SSL и таймаутом из настроек
            import httpx
            http_client = httpx.Client(verify=settings.ssl_verify, timeout=settings.llm_timeout_seconds)
            self.client = openai.OpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                http_client=http_client
            )
    
    def is_available(self) -> bool:
        return self.client is not None and settings.openai_api_key is not None
    
    async def generate_protocol(self, transcription: str, template_variables: Dict[str, str], diarization_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Генерировать протокол используя OpenAI GPT"""
        if not self.is_available():
            raise ValueError("OpenAI API не настроен")
        
        # Унифицированные системный и пользовательский промпты
        system_prompt = _build_system_prompt()
        user_prompt = _build_user_prompt(transcription, template_variables, diarization_data)
        
        try:
            # Диагностика запроса (без утечки полной транскрипции)
            base_url = settings.openai_base_url or "https://api.openai.com/v1"
            sys_msg = "Ты - строгий аналитик протоколов встреч..."
            user_len = len(user_prompt)
            transcript_len = len(transcription)
            vars_count = len(template_variables)
            logger.info(
                f"OpenAI запрос: model={settings.openai_model}, base_url={base_url}, "
                f"vars={vars_count}, transcription_chars={transcript_len}, prompt_chars={user_len}"
            )
            _snippet = user_prompt[:400].replace("\n", " ")
            logger.debug(f"OpenAI prompt (фрагмент 400): {_snippet}...")

            logger.info(f"Отправляем запрос в OpenAI с моделью {settings.openai_model}")
            # Выполняем синхронный вызов клиента в отдельном потоке, чтобы не блокировать event loop
            async def _call_openai():
                return await asyncio.to_thread(
                    self.client.chat.completions.create,
                    model=settings.openai_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.1,
                    response_format={"type": "json_object"}
                )
            response = await _call_openai()
            logger.info("Получен ответ от OpenAI API")
            
            content = response.choices[0].message.content
            logger.info(f"Получен ответ от OpenAI (длина: {len(content) if content else 0}): {content[:200] if content else 'None'}...")
            
            if not content or not content.strip():
                raise ValueError("Получен пустой ответ от OpenAI API")
            
            try:
                # Пытаемся распарсить как JSON напрямую (ожидается при response_format=json_object)
                return json.loads(content)
            except json.JSONDecodeError as e:
                # Мягкий парсер: пытаемся вырезать JSON из текста (как у Anthropic)
                logger.warning(f"Некорректный JSON (прямая загрузка). Пытаемся извлечь из текста: {e}")
                start_idx = content.find('{')
                end_idx = content.rfind('}') + 1
                json_str = content[start_idx:end_idx] if start_idx != -1 and end_idx > start_idx else content
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError as e2:
                    logger.error(f"Ошибка парсинга JSON ответа от OpenAI (после извлечения): {e2}")
                    logger.error(f"Содержимое ответа: {content}")
                    raise ValueError(f"Некорректный JSON в ответе от OpenAI: {e2}")
            
        except Exception as e:
            logger.error(f"Ошибка при работе с OpenAI API: {e}")
            raise


class AnthropicProvider(LLMProvider):
    """Провайдер для Anthropic Claude"""
    
    def __init__(self):
        self.client = None
        if settings.anthropic_api_key:
            # Создаем HTTP клиент с настройками SSL и таймаутом из настроек
            import httpx
            http_client = httpx.Client(verify=settings.ssl_verify, timeout=settings.llm_timeout_seconds)
            self.client = Anthropic(
                api_key=settings.anthropic_api_key,
                http_client=http_client
            )
    
    def is_available(self) -> bool:
        return self.client is not None and settings.anthropic_api_key is not None
    
    async def generate_protocol(self, transcription: str, template_variables: Dict[str, str], diarization_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Генерировать протокол используя Anthropic Claude"""
        if not self.is_available():
            raise ValueError("Anthropic API не настроен")
        
        # Унифицированные системный и пользовательский промпты
        system_prompt = _build_system_prompt()
        prompt = _build_user_prompt(transcription, template_variables, diarization_data)
        
        try:
            base_url = "Anthropic SDK"
            user_len = len(prompt)
            transcript_len = len(transcription)
            vars_count = len(template_variables)
            logger.info(
                f"Anthropic запрос: model=claude-3-haiku-20240307, base={base_url}, "
                f"vars={vars_count}, transcription_chars={transcript_len}, prompt_chars={user_len}"
            )
            _a_snippet = prompt[:400].replace("\n", " ")
            logger.debug(f"Anthropic prompt (фрагмент 400): {_a_snippet}...")
            # Выполняем синхронный вызов клиента Anthropic в отдельном потоке
            async def _call_anthropic():
                return await asyncio.to_thread(
                    self.client.messages.create,
                    model="claude-3-haiku-20240307",
                    max_tokens=2000,
                    temperature=0.1,
                    system=system_prompt,
                    messages=[
                        {"role": "user", "content": prompt}
                    ]
                )
            response = await _call_anthropic()
            
            content = response.content[0].text
            logger.info(f"Получен ответ от Anthropic (длина: {len(content) if content else 0}): {content[:200] if content else 'None'}...")
            
            if not content or not content.strip():
                raise ValueError("Получен пустой ответ от Anthropic API")
            
            # Пытаемся извлечь JSON из ответа
            start_idx = content.find('{')
            end_idx = content.rfind('}') + 1
            json_str = content[start_idx:end_idx] if start_idx != -1 and end_idx != 0 else content
            
            try:
                return json.loads(json_str)
            except json.JSONDecodeError as e:
                logger.error(f"Ошибка парсинга JSON ответа от Anthropic: {e}")
                logger.error(f"Содержимое ответа: {content}")
                raise ValueError(f"Некорректный JSON в ответе от Anthropic: {e}")
            
        except Exception as e:
            logger.error(f"Ошибка при работе с Anthropic API: {e}")
            raise


class YandexGPTProvider(LLMProvider):
    """Провайдер для Yandex GPT"""
    
    def __init__(self):
        self.api_key = settings.yandex_api_key
        self.folder_id = settings.yandex_folder_id
    
    def is_available(self) -> bool:
        return self.api_key is not None and self.folder_id is not None
    
    async def generate_protocol(self, transcription: str, template_variables: Dict[str, str], diarization_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Генерировать протокол используя Yandex GPT"""
        if not self.is_available():
            raise ValueError("Yandex GPT API не настроен")
        
        # Унифицированные системный и пользовательский промпты
        system_prompt = _build_system_prompt()
        prompt = _build_user_prompt(transcription, template_variables, diarization_data)
        
        headers = {
            "Authorization": f"Api-Key {self.api_key}",
            "Content-Type": "application/json"
        }
        
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
                
                if not content or not content.strip():
                    raise ValueError("Получен пустой ответ от Yandex GPT API")
                
                # Пытаемся извлечь JSON из ответа
                start_idx = content.find('{')
                end_idx = content.rfind('}') + 1
                json_str = content[start_idx:end_idx] if start_idx != -1 and end_idx != 0 else content
                
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError as e:
                    logger.error(f"Ошибка парсинга JSON ответа от Yandex GPT: {e}")
                    logger.error(f"Содержимое ответа: {content}")
                    raise ValueError(f"Некорректный JSON в ответе от Yandex GPT: {e}")
                
        except Exception as e:
            logger.error(f"Ошибка при работе с Yandex GPT API: {e}")
            raise


class LLMManager:
    """Менеджер для работы с различными LLM провайдерами"""
    
    def __init__(self):
        self.providers = {
            "openai": OpenAIProvider(),
            "anthropic": AnthropicProvider(),
            "yandex": YandexGPTProvider()
        }
    
    def get_available_providers(self) -> Dict[str, str]:
        """Получить список доступных провайдеров"""
        available = {}
        provider_names = {
            "openai": "OpenAI GPT",
            "anthropic": "Anthropic Claude",
            "yandex": "Yandex GPT"
        }
        
        for key, provider in self.providers.items():
            if provider.is_available():
                available[key] = provider_names[key]
        
        return available
    
    async def generate_protocol(self, provider_name: str, transcription: str, 
                              template_variables: Dict[str, str], diarization_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Генерировать протокол используя указанного провайдера"""
        if provider_name not in self.providers:
            raise ValueError(f"Неизвестный провайдер: {provider_name}")
        
        provider = self.providers[provider_name]
        if not provider.is_available():
            raise ValueError(f"Провайдер {provider_name} недоступен")
        
        return await provider.generate_protocol(transcription, template_variables, diarization_data)
    
    async def generate_protocol_with_fallback(self, preferred_provider: str, transcription: str, 
                                            template_variables: Dict[str, str], diarization_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Генерировать протокол с переключением на резервный провайдер в случае ошибки"""
        available_providers = list(self.get_available_providers().keys())
        
        if not available_providers:
            raise ValueError("Нет доступных LLM провайдеров")
        
        # Сначала пробуем предпочитаемый провайдер
        providers_to_try = [preferred_provider] if preferred_provider in available_providers else []
        # Добавляем остальные провайдеры как резервные
        for provider in available_providers:
            if provider not in providers_to_try:
                providers_to_try.append(provider)
        
        last_error = None
        for provider_name in providers_to_try:
            try:
                logger.info(f"Попытка генерации протокола с провайдером: {provider_name}")
                result = await self.generate_protocol(provider_name, transcription, template_variables, diarization_data)
                logger.info(f"Успешно сгенерирован протокол с провайдером: {provider_name}")
                return result
            except Exception as e:
                last_error = e
                logger.warning(f"Ошибка с провайдером {provider_name}: {e}")
                continue
        
        # Если все провайдеры не сработали
        raise ValueError(f"Все доступные провайдеры не сработали. Последняя ошибка: {last_error}")


# Глобальный экземпляр менеджера LLM
llm_manager = LLMManager()
