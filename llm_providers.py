"""
Модуль для интеграции с различными LLM провайдерами
"""

import json
import httpx
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
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


class OpenAIProvider(LLMProvider):
    """Провайдер для OpenAI GPT"""
    
    def __init__(self):
        self.client = None
        if settings.openai_api_key:
            openai.api_key = settings.openai_api_key
            # Создаем HTTP клиент с настройками SSL
            import httpx
            http_client = httpx.Client(verify=settings.ssl_verify)
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
        
        variables_str = "\n".join([f"- {key}: {desc}" for key, desc in template_variables.items()])
        
        # Формируем промпт с учетом диаризации
        if diarization_data and diarization_data.get("formatted_transcript"):
            transcription_text = f"""
Транскрипция с разделением говорящих:
{diarization_data["formatted_transcript"]}

Дополнительная информация:
- Количество говорящих: {diarization_data.get("total_speakers", "неизвестно")}
- Список говорящих: {", ".join(diarization_data.get("speakers", []))}

Исходная транскрипция (для справки):
{transcription}
"""
        else:
            transcription_text = f"""
Транскрипция:
{transcription}

Примечание: Диаризация (разделение говорящих) недоступна для этой записи.
"""
        
        prompt = f"""
Проанализируй следующую транскрипцию встречи и извлеки информацию для составления протокола.

{transcription_text}

Необходимо извлечь следующие переменные:
{variables_str}

При анализе обрати особое внимание на:
- Если доступна информация о говорящих, используй её для определения участников
- Выдели роли и вклад каждого участника в обсуждение
- Определи кто принимал ключевые решения
- Укажи кто получил какие задачи

Верни результат в формате JSON, где ключи - это названия переменных, а значения - извлеченная информация.
Если какая-то информация не найдена, используй "Не указано".

Пример ответа:
{{
    "participants": "Иван Иванов (руководитель), Мария Петрова (аналитик)",
    "date": "15.01.2024",
    "decisions": "Решено увеличить бюджет на маркетинг (решение принял Иван Иванов)"
}}
"""
        
        try:
            logger.info(f"Отправляем запрос в OpenAI с моделью {settings.openai_model}")
            response = self.client.chat.completions.create(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": "Ты - помощник для анализа встреч и составления протоколов. Отвечай только валидным JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3
            )
            logger.info("Получен ответ от OpenAI API")
            
            content = response.choices[0].message.content
            logger.info(f"Получен ответ от OpenAI (длина: {len(content) if content else 0}): {content[:200] if content else 'None'}...")
            
            if not content or not content.strip():
                raise ValueError("Получен пустой ответ от OpenAI API")
            
            try:
                return json.loads(content)
            except json.JSONDecodeError as e:
                logger.error(f"Ошибка парсинга JSON ответа от OpenAI: {e}")
                logger.error(f"Содержимое ответа: {content}")
                raise ValueError(f"Некорректный JSON в ответе от OpenAI: {e}")
            
        except Exception as e:
            logger.error(f"Ошибка при работе с OpenAI API: {e}")
            raise


class AnthropicProvider(LLMProvider):
    """Провайдер для Anthropic Claude"""
    
    def __init__(self):
        self.client = None
        if settings.anthropic_api_key:
            # Создаем HTTP клиент с настройками SSL
            import httpx
            http_client = httpx.Client(verify=settings.ssl_verify)
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
        
        variables_str = "\n".join([f"- {key}: {desc}" for key, desc in template_variables.items()])
        
        # Формируем промпт с учетом диаризации
        if diarization_data and diarization_data.get("formatted_transcript"):
            transcription_text = f"""
Транскрипция с разделением говорящих:
{diarization_data["formatted_transcript"]}

Дополнительная информация:
- Количество говорящих: {diarization_data.get("total_speakers", "неизвестно")}
- Список говорящих: {", ".join(diarization_data.get("speakers", []))}

Исходная транскрипция (для справки):
{transcription}
"""
        else:
            transcription_text = f"""
Транскрипция:
{transcription}

Примечание: Диаризация (разделение говорящих) недоступна для этой записи.
"""
        
        prompt = f"""
Проанализируй следующую транскрипцию встречи и извлеки информацию для составления протокола.

{transcription_text}

Необходимо извлечь следующие переменные:
{variables_str}

При анализе обрати особое внимание на:
- Если доступна информация о говорящих, используй её для определения участников
- Выдели роли и вклад каждого участника в обсуждение
- Определи кто принимал ключевые решения
- Укажи кто получил какие задачи

Верни результат в формате JSON, где ключи - это названия переменных, а значения - извлеченная информация.
Если какая-то информация не найдена, используй "Не указано".
"""
        
        try:
            response = self.client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=2000,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
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
        
        variables_str = "\n".join([f"- {key}: {desc}" for key, desc in template_variables.items()])
        
        # Формируем промпт с учетом диаризации
        if diarization_data and diarization_data.get("formatted_transcript"):
            transcription_text = f"""
Транскрипция с разделением говорящих:
{diarization_data["formatted_transcript"]}

Дополнительная информация:
- Количество говорящих: {diarization_data.get("total_speakers", "неизвестно")}
- Список говорящих: {", ".join(diarization_data.get("speakers", []))}

Исходная транскрипция (для справки):
{transcription}
"""
        else:
            transcription_text = f"""
Транскрипция:
{transcription}

Примечание: Диаризация (разделение говорящих) недоступна для этой записи.
"""
        
        prompt = f"""
Проанализируй следующую транскрипцию встречи и извлеки информацию для составления протокола.

{transcription_text}

Необходимо извлечь следующие переменные:
{variables_str}

При анализе обрати особое внимание на:
- Если доступна информация о говорящих, используй её для определения участников
- Выдели роли и вклад каждого участника в обсуждение
- Определи кто принимал ключевые решения
- Укажи кто получил какие задачи

Верни результат в формате JSON, где ключи - это названия переменных, а значения - извлеченная информация.
Если какая-то информация не найдена, используй "Не указано".
"""
        
        headers = {
            "Authorization": f"Api-Key {self.api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "modelUri": f"gpt://{self.folder_id}/yandexgpt-lite",
            "completionOptions": {
                "stream": False,
                "temperature": 0.3,
                "maxTokens": 2000
            },
            "messages": [
                {
                    "role": "system",
                    "text": "Ты - помощник для анализа встреч и составления протоколов. Отвечай только валидным JSON."
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
                    timeout=60.0
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
