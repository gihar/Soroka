"""Разбиение протокола на сообщения Telegram по границам секций.

Секция — блок канонического Markdown, начинающийся с ##-заголовка; всё до
первой секции (название встречи, шапка) — преамбула. Части собираются из целых
секций; если секция сама не помещается в лимит, она делится по строкам, и её
заголовок повторяется в следующей части с пометкой «(продолжение)».
"""

import re
from dataclasses import dataclass

from src.services.protocol_render.telegram_html import (
    _render_line,
    markdown_to_telegram_html,
)

_CONTINUATION_MARK = " (продолжение)"
_SECTION_HEADING_RE = re.compile(r"^##\s+")


@dataclass(frozen=True)
class _Block:
    """Отрендеренный блок протокола: заголовок секции (HTML) и строки содержимого."""

    heading: str | None
    lines: tuple[str, ...]


def _split_markdown_blocks(markdown_text: str) -> list[_Block]:
    """Разбить Markdown на преамбулу и секции, отрендерив строки в HTML."""
    blocks: list[_Block] = []
    heading: str | None = None
    lines: list[str] = []

    def close_block() -> None:
        nonlocal heading, lines
        trimmed = _trim_blank_edges(lines)
        if heading or trimmed:
            blocks.append(_Block(heading=heading, lines=tuple(trimmed)))
        heading, lines = None, []

    for raw_line in markdown_text.splitlines():
        if _SECTION_HEADING_RE.match(raw_line):
            close_block()
            heading = _render_line(raw_line)
            continue
        rendered = _render_line(raw_line)
        if rendered is not None:
            lines.append(rendered)
    close_block()
    return blocks


def _trim_blank_edges(lines: list[str]) -> list[str]:
    start, end = 0, len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def _continuation_heading(heading: str | None) -> str | None:
    if heading is None:
        return None
    if heading.endswith("</b>"):
        return f"{heading[: -len('</b>')]}{_CONTINUATION_MARK}</b>"
    return f"{heading}{_CONTINUATION_MARK}"


def _hard_wrap(line: str, limit: int) -> list[str]:
    """Разрезать строку длиннее лимита, не попадая внутрь HTML-сущности или тега."""
    if len(line) <= limit:
        return [line]
    pieces: list[str] = []
    rest = line
    while len(rest) > limit:
        cut = limit
        unsafe = max(rest.rfind("&", cut - 8, cut), rest.rfind("<", cut - 8, cut))
        if unsafe != -1 and ";" not in rest[unsafe:cut] and ">" not in rest[unsafe:cut]:
            cut = unsafe
        pieces.append(rest[:cut])
        rest = rest[cut:]
    pieces.append(rest)
    return pieces


def _block_text(heading: str | None, lines: list[str]) -> str:
    parts = ([heading] if heading else []) + lines
    return "\n".join(parts).strip()


def _split_oversized_block(block: _Block, max_length: int) -> list[str]:
    """Секция не помещается в лимит: делим по строкам, повторяя заголовок."""
    continuation = _continuation_heading(block.heading)
    overhead = (len(continuation) + 1) if continuation else 0
    line_budget = max(max_length - overhead, 1)

    chunks: list[str] = []
    heading = block.heading
    pending: list[str] = []
    for line in block.lines:
        for piece in _hard_wrap(line, line_budget):
            candidate = _block_text(heading, pending + [piece])
            if len(candidate) > max_length and (pending or heading):
                chunks.append(_block_text(heading, pending))
                heading, pending = continuation, []
            pending.append(piece)
    if pending or heading:
        chunks.append(_block_text(heading, pending))
    return [chunk for chunk in chunks if chunk]


def render_protocol_messages(markdown_text: str, max_length: int = 4000) -> list[str]:
    """Отрендерить протокол в Telegram HTML и разбить на сообщения по секциям."""
    html_text = markdown_to_telegram_html(markdown_text)
    if len(html_text) <= max_length:
        return [html_text] if html_text else []

    parts: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current.strip():
            parts.append(current.strip())
        current = ""

    def append(text: str) -> None:
        nonlocal current
        current = f"{current}\n\n{text}" if current else text

    for block in _split_markdown_blocks(markdown_text):
        block_text = _block_text(block.heading, list(block.lines))
        joined_len = len(current) + (2 if current else 0) + len(block_text)
        if joined_len <= max_length:
            append(block_text)
            continue
        if len(block_text) <= max_length:
            flush()
            append(block_text)
            continue
        flush()
        for chunk in _split_oversized_block(block, max_length):
            parts.append(chunk)
    flush()
    return parts
