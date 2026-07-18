"""
Protocol formatting utilities.

Extracted from ProcessingService to keep formatting logic separate from orchestration.
"""

import json
import re
from typing import Any, Dict

from loguru import logger

# Заглушки, которые LLM может вернуть вместо пустого значения. Рендерятся они
# как содержимое секции, поэтому до рендеринга приводятся к пустой строке —
# пустая секция не показывается вовсе (принцип «ничего пустого», PRODUCT.md).
_FILLER_RE = re.compile(
    r"^\s*(не\s+указано|нет\s+данных|не\s+определено|неизвестно"
    r"|отсутству(?:ет|ют)|нет|n/?a|none|[—–-])\s*\.?\s*$",
    re.IGNORECASE,
)


def _normalize_filler(value: Any) -> Any:
    """Заменить значение-заглушку («Не указано», «—», «N/A») пустой строкой."""
    if isinstance(value, str) and _FILLER_RE.match(value):
        return ""
    return value



_TRANSCRIPT_FALLBACK_NOTICE = (
    "⚠️ Не удалось структурировать протокол — ниже полная расшифровка встречи."
)


def _transcript_fallback(transcription_result) -> str:
    """Честная деградация: расшифровка не маскируется под протокол."""
    return (
        f"{_TRANSCRIPT_FALLBACK_NOTICE}\n\n"
        f"# Расшифровка встречи\n\n{transcription_result.transcription}"
    )


class ProtocolFormatter:
    """Formats LLM results into readable protocol text using templates."""

    def format_protocol(
        self,
        template: Any,
        llm_result: Any,
        transcription_result: Any,
    ) -> str:
        """Форматирование протокола с мягкой обработкой типов результата LLM"""
        from jinja2 import Template as Jinja2Template
        from jinja2 import meta

        # Если LLM вернул строку — считаем это готовым текстом протокола
        if isinstance(llm_result, str):
            text = llm_result.strip()
            if text:
                logger.info(f"LLM вернул готовый текст протокола (длина: {len(text)})")
                return text
            # Пустая строка — падаем на простой формат
            logger.warning("LLM вернул пустую строку, используем fallback")
            return _transcript_fallback(transcription_result)

        # Получаем содержимое шаблона
        if hasattr(template, 'content'):
            template_content = template.content
        elif isinstance(template, dict):
            template_content = template.get('content', '')
        else:
            template_content = str(template)

        # Если есть маппинг — используем Jinja2 для подстановки
        if isinstance(llm_result, dict):
            llm_result = {
                key: _normalize_filler(value) for key, value in llm_result.items()
            }
            logger.info("[DEBUG] Форматирование протокола с шаблоном")
            logger.info(f"[DEBUG] Тип шаблона: {type(template)}")
            logger.info(f"[DEBUG] Длина содержимого шаблона: {len(template_content)}")
            logger.info(f"[DEBUG] Тип LLM результата: {type(llm_result)}")
            logger.info(f"[DEBUG] Ключи в LLM результате: {list(llm_result.keys())[:10]}...")

            # Извлекаем переменные из шаблона
            try:
                jinja_template = Jinja2Template(template_content)
                template_variables = meta.find_undeclared_variables(
                    jinja_template.environment.parse(template_content)
                )
                logger.info(f"[DEBUG] Переменные в шаблоне: {sorted(list(template_variables))}")

                # Проверяем, какие переменные есть в LLM результате
                available_variables = set(llm_result.keys())
                missing_variables = template_variables - available_variables
                found_variables = template_variables & available_variables

                logger.info(f"[DEBUG] Найденные переменные: {sorted(list(found_variables))}")
                logger.info(f"[DEBUG] Отсутствующие переменные: {sorted(list(missing_variables))}")

                # Анализ совместимости шаблона и LLM данных
                if template_variables:
                    compatibility_score = len(found_variables) / len(template_variables)
                    logger.info(
                        f"[DEBUG] Совместимость шаблона: {compatibility_score:.1%} "
                        f"({len(found_variables)}/{len(template_variables)} переменных)"
                    )

                    if compatibility_score < 0.4:
                        logger.warning(
                            f"Низкая совместимость шаблона ({compatibility_score:.1%}) "
                            "- рекомендуется другой шаблон"
                        )
                        llm_only_variables = available_variables - template_variables
                        if llm_only_variables:
                            important_llm_vars = [
                                var for var in llm_only_variables
                                if var in [
                                    'agenda', 'key_points', 'decisions',
                                    'action_items', 'discussion', 'meeting_title',
                                ]
                            ]
                            if important_llm_vars:
                                logger.warning(
                                    f"Важные поля LLM отсутствуют в шаблоне: {important_llm_vars}"
                                )

                    elif compatibility_score >= 0.7:
                        logger.info(f"Хорошая совместимость шаблона ({compatibility_score:.1%})")

                # Добавляем пустые значения для отсутствующих переменных
                if missing_variables:
                    logger.warning(
                        f"Добавляю пустые значения для отсутствующих переменных: {missing_variables}"
                    )
                    for var in missing_variables:
                        llm_result[var] = ''

                # Проверяем наличие важных полей
                important_fields = ['meeting_title', 'participants', 'discussion', 'decisions']
                missing_important = [
                    field for field in important_fields
                    if not llm_result.get(field, '').strip()
                ]
                if missing_important:
                    logger.warning(f"Отсутствуют важные поля: {missing_important}")
                else:
                    logger.info("Все важные поля присутствуют и не пусты")

                # Пробуем отрендерить шаблон
                try:
                    rendered_result = jinja_template.render(**llm_result)
                    result_length = len(rendered_result.strip())
                    logger.info(
                        f"[DEBUG] Шаблон успешно отрендерен. Длина результата: {result_length}"
                    )

                    if result_length > 50:
                        return rendered_result
                    else:
                        logger.warning(
                            f"Результат рендеринга слишком короткий "
                            f"({result_length} символов), используем fallback"
                        )

                except Exception as render_error:
                    logger.error(f"Ошибка при рендеринге шаблона: {render_error}")
                    logger.error(f"Тип ошибки: {type(render_error)}")
                    logger.error(f"Детали ошибки: {str(render_error)}")

            except Exception as template_error:
                logger.error(f"Ошибка при анализе шаблона: {template_error}")
                logger.error(f"Тип ошибки: {type(template_error)}")

        # Enhanced Fallback
        if isinstance(llm_result, dict):
            return self._format_enhanced_fallback(llm_result, transcription_result)

        # Последний fallback: базовый текст транскрипции
        logger.error("Используем последний fallback - базовую транскрипцию")
        return _transcript_fallback(transcription_result)

    def convert_complex_to_markdown(self, value: Any) -> str:
        """Преобразовать сложные типы (dict, list) в читаемый Markdown-текст"""
        if isinstance(value, str):
            return self.fix_json_in_text(value)

        if isinstance(value, dict):
            return self.format_dict_to_text(value)

        if isinstance(value, list):
            return self.format_list_to_text(value)

        return str(value)

    def format_dict_to_text(self, data: dict) -> str:
        """Форматировать словарь в читаемый текст"""

        # Структура времени/даты с milestones, constraints
        if 'constraints' in data or 'milestones' in data or 'meetings' in data:
            parts = []
            if 'constraints' in data:
                constraints = data['constraints']
                if isinstance(constraints, list):
                    parts.append("Ограничения:\n" + "\n".join([f"- {c}" for c in constraints]))
            if 'milestones' in data:
                milestones = data['milestones']
                if isinstance(milestones, list):
                    milestone_texts = []
                    for m in milestones:
                        if isinstance(m, dict):
                            date = m.get('date', '')
                            event = m.get('event', '')
                            milestone_texts.append(f"- {date}: {event}")
                        else:
                            milestone_texts.append(f"- {m}")
                    parts.append("Важные даты:\n" + "\n".join(milestone_texts))
            if 'meetings' in data:
                meetings = data['meetings']
                if isinstance(meetings, list):
                    meeting_texts = []
                    for m in meetings:
                        if isinstance(m, dict):
                            slot = m.get('slot', '')
                            event = m.get('event', '')
                            meeting_texts.append(f"- {slot}: {event}")
                        else:
                            meeting_texts.append(f"- {m}")
                    parts.append("Встречи:\n" + "\n".join(meeting_texts))
            return "\n\n".join(parts)

        # Структура участника с name и role
        if 'name' in data and 'role' in data:
            name = data.get('name', '')
            role = data.get('role', '')
            notes = data.get('notes', '')
            if notes:
                return f"{name} ({role}): {notes}"
            return f"{name} ({role})" if role else name

        # Структура решения с decision
        if 'decision' in data:
            decision = data.get('decision', '')
            decision_maker = data.get('decision_maker', '')
            if decision_maker and decision_maker != 'Не указано':
                return f"- {decision} (решение принял: {decision_maker})"
            return f"- {decision}"

        # Структура задачи с item; неизвестные части опускаются, не заполняются заглушкой
        if 'item' in data or 'task' in data:
            item = data.get('item', data.get('task', ''))
            assignee = _normalize_filler(data.get('assignee', ''))
            due = _normalize_filler(data.get('due', ''))
            text = f"- {item}"
            if assignee:
                text += f" — Ответственный: {assignee}"
            if due:
                text += f", срок: {due}" if assignee else f" — срок: {due}"
            return text

        # Общий случай - key: value пары
        lines = []
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                v_str = self.convert_complex_to_markdown(v)
                lines.append(f"**{k}:** {v_str}")
            else:
                lines.append(f"**{k}:** {v}")
        return "\n".join(lines)

    def format_list_to_text(self, data: list) -> str:
        """Форматировать список в читаемый текст"""
        if not data:
            return ""

        first = data[0]

        if isinstance(first, dict):
            items = []
            for item in data:
                formatted = self.format_dict_to_text(item)
                if formatted.strip().startswith('-'):
                    items.append(formatted.strip())
                else:
                    items.append(f"- {formatted}")
            return "\n".join(items)

        return "\n".join([f"- {item}" for item in data])

    def fix_json_in_text(self, text: str) -> str:
        """Исправляет JSON-структуры в тексте, преобразуя их в читаемый формат"""
        json_pattern = r'\{[^{}]*\}'

        def replace_json_object(match):
            json_str = match.group(0)
            try:
                json_obj = json.loads(json_str)

                if isinstance(json_obj, dict):
                    if 'decision' in json_obj:
                        decision = json_obj.get('decision', '')
                        decision_maker = _normalize_filler(json_obj.get('decision_maker', ''))
                        if decision_maker:
                            return f"\u2022 {decision} (решение принял: {decision_maker})"
                        return f"\u2022 {decision}"
                    elif 'item' in json_obj:
                        item = json_obj.get('item', '')
                        assignee = _normalize_filler(json_obj.get('assignee', ''))
                        due = _normalize_filler(json_obj.get('due', ''))
                        item_text = f"\u2022 {item}"
                        if assignee:
                            item_text += f" - {assignee}"
                        if due:
                            item_text += f", до {due}"
                        return item_text
                    else:
                        values = [
                            str(v) for v in json_obj.values() if _normalize_filler(v)
                        ]
                        return ' - '.join(values)

            except (json.JSONDecodeError, TypeError):
                pass

            return json_str

        result = re.sub(json_pattern, replace_json_object, text)
        result = re.sub(r'},\s*\{', '\n', result)
        result = re.sub(r'^\s*,\s*', '', result, flags=re.MULTILINE)

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _format_enhanced_fallback(
        self,
        llm_result: Dict[str, Any],
        transcription_result: Any,
    ) -> str:
        """Enhanced fallback: build protocol from LLM fields in priority order."""
        logger.warning("Используем enhanced fallback с данными LLM")

        field_priority = [
            ('meeting_title', 'Протокол встречи'),
            ('meeting_date', None), ('meeting_time', None),
            ('participants', 'Участники'),
            ('agenda', 'Повестка дня'),
            ('discussion', 'Ход обсуждения'),
            ('key_points', 'Ключевые моменты и выводы'),
            ('decisions', 'Принятые решения'),
            ('action_items', 'Поручения и ответственные'),
            ('tasks', 'Распределение задач'),
            ('next_steps', 'Следующие шаги'),
            ('deadlines', 'Сроки выполнения'),
            ('risks_and_blockers', 'Риски и блокеры'),
            ('issues', 'Выявленные проблемы'),
            ('questions', 'Открытые вопросы'),
            ('next_meeting', 'Следующая встреча'),
            ('additional_notes', 'Дополнительные заметки'),
            ('technical_issues', 'Технические вопросы'),
            ('architecture_decisions', 'Архитектурные решения'),
            ('technical_tasks', 'Технические задачи'),
            ('learning_objectives', 'Цели обучения'),
            ('key_concepts', 'Ключевые концепции'),
            ('examples_and_cases', 'Примеры и кейсы'),
            ('next_sprint_plans', 'Планы на следующий спринт'),
        ]

        protocol_parts = []
        used_sections = []

        title = llm_result.get('meeting_title', '').strip() or 'Протокол встречи'
        protocol_parts.append(f"# {title}")

        date = llm_result.get('meeting_date', llm_result.get('date', '')).strip()
        time_val = llm_result.get('meeting_time', llm_result.get('time', '')).strip()

        if date or time_val:
            datetime_parts = []
            if date:
                datetime_parts.append(f"**Дата:** {date}")
            if time_val:
                datetime_parts.append(f"**Время:** {time_val}")
            if datetime_parts:
                protocol_parts.append(" | ".join(datetime_parts))

        participants = llm_result.get('participants', '').strip()
        if participants:
            protocol_parts.append(f"**Участники:**\n{participants}")

        for field, section_name in field_priority[4:]:
            content = llm_result.get(field, '').strip()
            if content and section_name:
                protocol_parts.append(f"\n## {section_name}\n{content}")
                used_sections.append(field)

        total_fields = len([f for f, _ in field_priority if llm_result.get(f, '').strip()])
        logger.info(f"Enhanced fallback использован {total_fields} полей: {used_sections}")

        fallback_result = '\n\n'.join(protocol_parts)
        result_length = len(fallback_result)
        logger.info(f"Enhanced fallback создан. Длина: {result_length} символов")

        if result_length > 200:
            return fallback_result
        else:
            logger.warning(
                f"Enhanced fallback результат слишком короткий ({result_length}), "
                "используем базовый fallback"
            )

        logger.error("Используем последний fallback - базовую транскрипцию")
        return _transcript_fallback(transcription_result)
