"""Рендер канонического Markdown протокола в Telegram HTML.

Telegram parse_mode="Markdown" (legacy) не понимает #-заголовки и **жирный**:
в чате они видны буквально. Канонический формат протокола остаётся Markdown
(файл .md, PDF), а для чата этот модуль переводит его в HTML-разметку Telegram:
заголовки -> <b>, **x** -> <b>x</b>, `x` -> <code>x</code>, маркеры списков -> «•».

Непарные маркеры остаются буквальным текстом, HTML-спецсимволы экранируются,
поэтому результат всегда валиден для parse_mode="HTML".
"""

import html
import re

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^(\s*)[-*]\s+(.*)$")
_HR_RE = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_CODE_RE = re.compile(r"`([^`]+)`")
_FENCE_RE = re.compile(r"^\s*```")


def escape_telegram_html(text: str) -> str:
    """Экранировать текст для parse_mode="HTML": только «&», «<» и «>».

    Единственная таблица экранирования Telegram HTML на весь бот (ADR-0005):
    и тело протокола, и интерактивные экраны берут её отсюда, а не плодят копии.
    """
    return html.escape(text, quote=False)


def _render_inline(text: str) -> str:
    """Экранировать HTML и преобразовать инлайн-разметку одной строки."""
    with_code = _CODE_RE.sub(r"<code>\1</code>", escape_telegram_html(text))
    return _BOLD_RE.sub(r"<b>\1</b>", with_code)


def _render_line(line: str) -> str | None:
    """Преобразовать строку Markdown в строку HTML; None — строка опускается."""
    if _HR_RE.match(line):
        return None

    heading = _HEADING_RE.match(line)
    if heading:
        return f"<b>{_render_inline(heading.group(2).strip())}</b>"

    bullet = _BULLET_RE.match(line)
    if bullet:
        indent, content = bullet.groups()
        return f"{indent}• {_render_inline(content)}"

    return _render_inline(line)


def markdown_to_telegram_html(markdown_text: str) -> str:
    """Перевести Markdown-протокол в текст для parse_mode="HTML".

    ```-фенсы становятся <pre>: содержимое экранируется и не трогается
    инлайн-разметкой. Незакрытый фенс не теряет контент.
    """
    rendered_lines: list[str] = []
    code_lines: list[str] = []
    in_code = False

    def close_code_block() -> None:
        nonlocal code_lines
        if code_lines:
            escaped = html.escape("\n".join(code_lines), quote=False)
            rendered_lines.append(f"<pre>{escaped}</pre>")
        code_lines = []

    for line in markdown_text.splitlines():
        if _FENCE_RE.match(line):
            if in_code:
                close_code_block()
            in_code = not in_code
            continue
        if in_code:
            code_lines.append(line)
            continue
        rendered = _render_line(line)
        if rendered is not None:
            rendered_lines.append(rendered)
    close_code_block()

    joined = "\n".join(rendered_lines)
    return re.sub(r"\n{3,}", "\n\n", joined).strip("\n")
