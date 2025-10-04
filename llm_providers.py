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
    async def generate_protocol(self, transcription: str, template_variables: Dict[str, str], diarization_data: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
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
        "Ты — профессиональный протоколист высшей квалификации с опытом документирования "
        "деловых встреч, совещаний и переговоров.\n\n"
        
        "ТВОЯ РОЛЬ:\n"
        "- Извлекать и структурировать ключевую информацию из стенограмм встреч\n"
        "- Создавать четкие, лаконичные и информативные протоколы\n"
        "- Сохранять объективность и фактологическую точность\n\n"
        
        "ПРИНЦИПЫ РАБОТЫ:\n"
        "1. ТОЧНОСТЬ: Используй только факты, явно присутствующие в стенограмме\n"
        "2. НЕТ ДОМЫСЛОВ: Не додумывай, не интерпретируй, не добавляй информацию от себя\n"
        "3. КОНТЕКСТ: Если упоминается роль/должность/срок/сумма — укажи их; если нет — не придумывай\n"
        "4. КРАТКОСТЬ: Излагай суть без воды, избегай избыточных деталей\n"
        "5. ТЕРМИНОЛОГИЯ: Сохраняй профессиональные термины и названия как в оригинале\n"
        "6. СТИЛЬ: Официально-деловой язык без разговорных оборотов\n\n"
        
        "ЧТО ИГНОРИРОВАТЬ:\n"
        "- Междометия (э-э, м-м, ну, вот)\n"
        "- Повторы и запинки\n"
        "- Вводные фразы без смысловой нагрузки\n"
        "- Отвлеченные разговоры не по теме встречи\n\n"
        
        "ЧТО ВЫДЕЛЯТЬ:\n"
        "- Конкретные решения и резолюции\n"
        "- Поручения с указанием исполнителей (если упомянуты)\n"
        "- Сроки, суммы, показатели (только если явно названы)\n"
        "- Ключевые проблемы и их решения\n"
        "- Согласованные договоренности\n\n"
        
        "ФОРМАТ ВЫВОДА:\n"
        "Строго валидный JSON-объект без обрамления в markdown, без комментариев, без пояснений. "
        "Если данные отсутствуют или неоднозначны — используй 'Не указано'."
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
        "═══════════════════════════════════════════════════════════\n"
        "ИСХОДНЫЕ ДАННЫЕ ДЛЯ АНАЛИЗА\n"
        "═══════════════════════════════════════════════════════════\n\n"
        f"{transcription_text}\n"
        "═══════════════════════════════════════════════════════════\n"
        "ПОЛЯ ДЛЯ ИЗВЛЕЧЕНИЯ\n"
        "═══════════════════════════════════════════════════════════\n\n"
        f"{variables_str}\n\n"
        "═══════════════════════════════════════════════════════════\n"
        "ИНСТРУКЦИИ ПО ИЗВЛЕЧЕНИЮ\n"
        "═══════════════════════════════════════════════════════════\n\n"
        
        "📋 СТРУКТУРА ВЫВОДА:\n"
        "- Верни только валидный JSON-объект (без ```json, без markdown)\n"
        "- Используй СТРОГО эти ключи из списка полей\n"
        "- Сохраняй порядок ключей как в списке выше\n"
        "- Каждое значение — строка (UTF-8), БЕЗ вложенных объектов или массивов\n\n"
        
        "📝 ФОРМАТИРОВАНИЕ ТЕКСТА:\n"
        "- Для списков/перечислений: каждый пункт с новой строки, начинай с '- ' (дефис + пробел)\n"
        "- НЕ используй нумерацию (1. 2. 3.), только дефисы\n"
        "- НЕ ставь точку в конце пункта списка\n"
        "- Для имен/участников: разделяй точкой с запятой (;)\n"
        "- Для дат/времени: сохраняй формат как упомянут в тексте\n\n"
        
        "🎯 ИЗВЛЕЧЕНИЕ ДАННЫХ:\n"
        "- Используй ТОЛЬКО факты из транскрипции\n"
        "- Если информация упомянута с контекстом (роль, срок, сумма) — укажи полностью\n"
        "- Если данные отсутствуют, неоднозначны или неясны — пиши 'Не указано'\n"
        "- Убирай дубликаты, объединяй идентичные пункты\n"
        "- Сохраняй хронологию: порядок пунктов = порядок в тексте\n\n"
        
        "🔍 ОБРАБОТКА ИНФОРМАЦИИ О ГОВОРЯЩИХ:\n"
        "- Если доступна диаризация: используй метки 'Спикер 1:', 'Спикер 2:' и т.д.\n"
        "- Определяй ответственных за действия по контексту их высказываний\n"
        "- Указывай кто принял решение или взял на себя обязательство\n"
        "- Формат: 'Задача — Ответственный: [имя или Спикер N]'\n\n"
        
        "🧹 ЧТО ОТФИЛЬТРОВЫВАТЬ:\n"
        "- Междометия, запинки, повторы слов\n"
        "- Вводные фразы без смысловой нагрузки\n"
        "- Разговоры не по теме встречи\n"
        "- Технические комментарии ('не слышно', 'повторите' и т.д.)\n\n"
        
        "═══════════════════════════════════════════════════════════\n"
        "ПРИМЕРЫ ПРАВИЛЬНОГО ФОРМАТИРОВАНИЯ\n"
        "═══════════════════════════════════════════════════════════\n\n"
        
        "✅ ПРАВИЛЬНО:\n"
        "{\n"
        "  \"participants\": \"Иван Иванов, директор; Мария Петрова, руководитель отдела продаж; Алексей Сидоров\",\n"
        "  \"main_topic\": \"Планирование маркетинговой кампании на Q2 2024\",\n"
        "  \"decisions\": \"- Увеличить бюджет на digital-маркетинг на 30%\\n- Утвердить новую стратегию продвижения в социальных сетях\\n- Отложить запуск рекламы на ТВ до следующего квартала\",\n"
        "  \"action_items\": \"- Подготовить презентацию новой стратегии к 15 марта — Ответственный: Мария Петрова\\n- Согласовать бюджет с финансовым отделом — Ответственный: Иван Иванов\\n- Провести анализ конкурентов — Ответственный: отдел маркетинга\",\n"
        "  \"deadlines\": \"- Презентация стратегии: 15 марта 2024\\n- Согласование бюджета: до конца текущей недели\\n- Анализ конкурентов: к следующему совещанию\",\n"
        "  \"issues\": \"- Недостаточный охват целевой аудитории текущими каналами\\n- Высокая стоимость привлечения клиента\\n- Необходимость обновления креативов\"\n"
        "}\n\n"
        
        "❌ НЕПРАВИЛЬНО:\n"
        "{\n"
        "  \"participants\": [\"Иван\", \"Мария\"],  ❌ массив вместо строки\n"
        "  \"decisions\": \"1) Решение один 2) Решение два.\",  ❌ нумерация + точки\n"
        "  \"action_items\": \"Подготовить презентацию (Мария)\",  ❌ без дефиса, неправильный формат\n"
        "  \"deadlines\": \"Срочно, как можно быстрее\",  ❌ нет конкретики, хотя она могла быть\n"
        "  \"extra_field\": \"...\",  ❌ поле не из списка\n"
        "  \"budget\": \"50000 рублей (предположительно)\"  ❌ домыслы в скобках\n"
        "}\n\n"
        
        "═══════════════════════════════════════════════════════════\n"
        "СПЕЦИФИЧНЫЕ ПРАВИЛА ПО ТИПАМ ПОЛЕЙ\n"
        "═══════════════════════════════════════════════════════════\n\n"
        
        "👥 Участники (participants):\n"
        "- Формат: 'Имя Фамилия[, должность][; Следующий участник]'\n"
        "- Должность указывай только если явно названа\n"
        "- Если имена не упомянуты: 'Спикер 1; Спикер 2; Спикер 3'\n\n"
        
        "📌 Решения (decisions):\n"
        "- Только согласованные, утвержденные решения\n"
        "- Формулировка должна отражать суть без лишних слов\n"
        "- Если есть условия — укажи их коротко\n\n"
        
        "✅ Задачи/поручения (action_items):\n"
        "- Формат: '- Описание задачи — Ответственный: [имя/роль/Спикер N]'\n"
        "- Если ответственный не назван явно, но понятен из контекста — укажи\n"
        "- Если непонятно кто ответственный: '- Описание задачи — Ответственный: Не указано'\n\n"
        
        "⏰ Сроки (deadlines):\n"
        "- Формат: '- Задача/событие: конкретный срок'\n"
        "- Сохраняй формат дат как в оригинале\n"
        "- Относительные сроки: 'к концу недели', 'к следующей встрече'\n\n"
        
        "⚠️ Проблемы/вопросы (issues/questions):\n"
        "- Формулируй суть проблемы кратко\n"
        "- Убирай эмоциональную окраску, оставляй факты\n"
        "- Группируй связанные проблемы в один пункт\n\n"
        
        "═══════════════════════════════════════════════════════════\n\n"
        
        "НАЧИНАЙ АНАЛИЗ. Верни только JSON без дополнительных комментариев.\n"
    )
    return user_prompt


class OpenAIProvider(LLMProvider):
    """Провайдер для OpenAI GPT"""
    
    def __init__(self):
        self.client = None
        self.http_client = None
        if settings.openai_api_key:
            openai.api_key = settings.openai_api_key
            # Создаем HTTP клиент с настройками SSL и таймаутом из настроек
            import httpx
            self.http_client = httpx.Client(verify=settings.ssl_verify, timeout=settings.llm_timeout_seconds)
            self.client = openai.OpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                http_client=self.http_client
            )
    
    def is_available(self) -> bool:
        return self.client is not None and settings.openai_api_key is not None
    
    async def generate_protocol(self, transcription: str, template_variables: Dict[str, str], diarization_data: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """Генерировать протокол используя OpenAI GPT"""
        if not self.is_available():
            raise ValueError("OpenAI API не настроен")
        
        # Унифицированные системный и пользовательский промпты
        system_prompt = _build_system_prompt()
        user_prompt = _build_user_prompt(transcription, template_variables, diarization_data)
        
        try:
            # Выбор пресета модели, если передан ключ
            selected_model = settings.openai_model
            selected_base_url = settings.openai_base_url or "https://api.openai.com/v1"
            model_key = kwargs.get("openai_model_key")
            if model_key:
                try:
                    preset = next((p for p in settings.openai_models if p.key == model_key), None)
                except Exception:
                    preset = None
                if preset:
                    selected_model = preset.model
                    if getattr(preset, 'base_url', None):
                        selected_base_url = preset.base_url
            
            # Клиент для нужного base_url (по умолчанию используем self.client)
            client = self.client
            if client is None or (selected_base_url and getattr(client, 'base_url', None) != selected_base_url):
                client = openai.OpenAI(
                    api_key=settings.openai_api_key,
                    base_url=selected_base_url,
                    http_client=self.http_client
                )

            # Диагностика запроса (без утечки полной транскрипции)
            base_url = selected_base_url or "https://api.openai.com/v1"
            sys_msg = "Ты - строгий аналитик протоколов встреч..."
            user_len = len(user_prompt)
            transcript_len = len(transcription)
            vars_count = len(template_variables)
            logger.info(
                f"OpenAI запрос: model={selected_model}, base_url={base_url}, "
                f"vars={vars_count}, transcription_chars={transcript_len}, prompt_chars={user_len}"
            )
            _snippet = user_prompt[:400].replace("\n", " ")
            logger.debug(f"OpenAI prompt (фрагмент 400): {_snippet}...")

            logger.info(f"Отправляем запрос в OpenAI с моделью {selected_model}")
            # Выполняем синхронный вызов клиента в отдельном потоке, чтобы не блокировать event loop
            async def _call_openai():
                return await asyncio.to_thread(
                    client.chat.completions.create,
                    model=selected_model,
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
    
    async def generate_protocol(self, transcription: str, template_variables: Dict[str, str], diarization_data: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
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
    
    async def generate_protocol(self, transcription: str, template_variables: Dict[str, str], diarization_data: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
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
                              template_variables: Dict[str, str], diarization_data: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """Генерировать протокол используя указанного провайдера"""
        if provider_name not in self.providers:
            raise ValueError(f"Неизвестный провайдер: {provider_name}")
        
        provider = self.providers[provider_name]
        if not provider.is_available():
            raise ValueError(f"Провайдер {provider_name} недоступен")
        
        # Передаем дополнительные аргументы (например, openai_model_key)
        return await provider.generate_protocol(transcription, template_variables, diarization_data, **kwargs)
    
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
