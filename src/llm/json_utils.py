"""Safe JSON parsing utilities for LLM responses."""
import json
import re
from typing import Dict, Any
from loguru import logger


def safe_json_parse(content: str, context: str = "LLM response") -> Dict[str, Any]:
    """
    Safe JSON parsing with handling of various edge cases.

    Args:
        content: String with JSON to parse
        context: Context for logging (e.g., "OpenAI response")

    Returns:
        Parsed JSON dict

    Raises:
        ValueError: If JSON parsing fails after all attempts
    """
    if not content or not content.strip():
        raise ValueError(f"Получен пустой ответ в {context}")

    original_content = content
    content_length = len(content)

    # Step 1: Remove BOM and invisible characters
    content = content.strip()
    if content.startswith('\ufeff'):
        content = content[1:]
        logger.debug(f"Удален BOM из {context}")

    # Step 2: Direct parse attempt
    try:
        result = json.loads(content)
        logger.debug(f"Прямой парсинг JSON успешен для {context}")
        return result
    except json.JSONDecodeError as e:
        logger.warning(f"Прямой парсинг JSON не удался для {context}: {e}")

    # Step 3: Remove markdown blocks (```json ... ``` or ``` ... ```)
    markdown_pattern = r'```(?:json)?\s*\n?(.*?)\n?```'
    markdown_match = re.search(markdown_pattern, content, re.DOTALL)
    if markdown_match:
        content = markdown_match.group(1).strip()
        logger.debug(f"Извлечен JSON из markdown блока в {context}")
        try:
            result = json.loads(content)
            logger.info(f"Парсинг JSON после удаления markdown успешен для {context}")
            return result
        except json.JSONDecodeError as e:
            logger.warning(f"Парсинг после удаления markdown не удался для {context}: {e}")

    # Step 4: Find JSON object in text (between first { and last })
    start_idx = content.find('{')
    end_idx = content.rfind('}') + 1

    if start_idx != -1 and end_idx > start_idx:
        json_str = content[start_idx:end_idx]
        logger.debug(f"Извлечен JSON из позиции {start_idx} до {end_idx} в {context}")
        try:
            result = json.loads(json_str)
            logger.info(f"Парсинг извлеченного JSON успешен для {context}")
            return result
        except json.JSONDecodeError as e:
            logger.warning(f"Парсинг извлеченного JSON не удался для {context}: {e}")

    # Step 5: Try to find JSON array (between first [ and last ])
    start_idx = content.find('[')
    end_idx = content.rfind(']') + 1

    if start_idx != -1 and end_idx > start_idx:
        json_str = content[start_idx:end_idx]
        logger.debug(f"Извлечен JSON массив из позиции {start_idx} до {end_idx} в {context}")
        try:
            result = json.loads(json_str)
            logger.info(f"Парсинг JSON массива успешен для {context}")
            return result
        except json.JSONDecodeError as e:
            logger.warning(f"Парсинг JSON массива не удался для {context}: {e}")

    # Step 6: Last attempt - remove comments and trailing commas
    try:
        content_no_comments = re.sub(r'//.*?$', '', content, flags=re.MULTILINE)
        content_no_comments = re.sub(r'/\*.*?\*/', '', content_no_comments, flags=re.DOTALL)
        content_no_comments = re.sub(r',(\s*[}\]])', r'\1', content_no_comments)

        result = json.loads(content_no_comments)
        logger.info(f"Парсинг JSON после очистки комментариев успешен для {context}")
        return result
    except json.JSONDecodeError:
        pass

    # All attempts exhausted
    logger.error(f"Не удалось распарсить JSON в {context}")
    logger.error(f"Длина ответа: {content_length} символов")
    logger.error(f"Первые 500 символов: {original_content[:500]}")
    logger.error(f"Последние 500 символов: {original_content[-500:] if len(original_content) > 500 else ''}")

    try:
        json.loads(original_content)
    except json.JSONDecodeError as final_error:
        error_pos = getattr(final_error, 'pos', None)
        if error_pos and error_pos < len(original_content):
            start = max(0, error_pos - 50)
            end = min(len(original_content), error_pos + 50)
            context_str = original_content[start:end]
            logger.error(f"Контекст ошибки (позиция {error_pos}): ...{context_str}...")

        raise ValueError(
            f"Не удалось распарсить JSON в {context}: {final_error}. "
            f"Длина: {content_length} символов. "
            f"Проверьте логи для подробностей."
        )

    raise ValueError(f"Не удалось распарсить JSON в {context}. Длина: {content_length} символов.")
