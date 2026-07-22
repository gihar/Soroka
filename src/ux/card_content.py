"""Семантическое содержимое интерактивных экранов и его рендер (ADR-0005).

Экран описывается семантически — заголовком и строками спикеров, — а разметку
добавляет рендер: Telegram HTML для чата (экранирование только «&», «<», «>»,
как тело протокола в ADR-0001) и plain-страховка, которая несёт то же
содержимое без тегов. Отправитель карточек (``card_sender``) выбирает между
ними: HTML в норме, plain — единственный фолбэк.
"""

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

from src.services.protocol_render.telegram_html import escape_telegram_html

_SEPARATOR = "────────────────────────"
_NOT_DEFINED = "Не определен"


@runtime_checkable
class CardContent(Protocol):
    """Содержимое экрана, умеющее отрисоваться в HTML и в plain-страховку."""

    def to_html(self) -> str: ...

    def to_plain(self) -> str: ...


@dataclass(frozen=True)
class SpeakerRow:
    """Строка одного спикера: подпись и (опционально) цитата для опознания.

    ``display_name is None`` — спикер не сопоставлен («Не определен»).
    """

    speaker_id: str
    display_name: Optional[str]
    quote: Optional[str] = None


@dataclass(frozen=True)
class MappingCard:
    """Карточка сопоставления: заголовок, строки спикеров и опциональная подсказка.

    Заголовок ветвится вызывающим (ADR-0002): «Проверьте сопоставление» при
    наличии списка участников, «Назовите спикеров (по желанию)» без него.
    ``hint`` — необязательная строка-следствие внизу карточки (nudge о том, что
    неназванные спикеры уйдут метками); задаёт её вызывающий, только когда есть
    несопоставленные спикеры. Пустая подсказка строк не добавляет.
    """

    header: str
    rows: tuple[SpeakerRow, ...] = ()
    hint: Optional[str] = None

    def to_html(self) -> str:
        """Разметка Telegram HTML: жирные заголовок и спикеры, цитаты в кавычках."""
        lines = [f"🎭 <b>{escape_telegram_html(self.header)}</b>", ""]
        for row in self.rows:
            speaker = f"<b>{escape_telegram_html(row.speaker_id)}</b>"
            if row.display_name:
                lines.append(f"{speaker} → {escape_telegram_html(row.display_name)} ✓")
            else:
                lines.append(f"{speaker} → {escape_telegram_html(_NOT_DEFINED)} ❓")
            if row.quote:
                lines.append(f'  "{escape_telegram_html(row.quote)}"')
            lines.append("")
        if self.hint:
            lines.append(f"<i>{escape_telegram_html(self.hint)}</i>")
        lines.append(_SEPARATOR)
        return "\n".join(lines)

    def to_plain(self) -> str:
        """Plain-страховка: то же содержимое без тегов и без экранирования."""
        lines = [f"🎭 {self.header}", ""]
        for row in self.rows:
            if row.display_name:
                lines.append(f"{row.speaker_id} → {row.display_name} ✓")
            else:
                lines.append(f"{row.speaker_id} → {_NOT_DEFINED} ❓")
            if row.quote:
                lines.append(f'  "{row.quote}"')
            lines.append("")
        if self.hint:
            lines.append(self.hint)
        lines.append(_SEPARATOR)
        return "\n".join(lines)


@dataclass(frozen=True)
class PlainCard:
    """Простой текстовый экран (подсказка): без жирного и строк спикеров.

    Тот же путь доставки, что и карточка: HTML-рендер лишь экранирует текст,
    plain-страховка отдаёт его как есть.
    """

    text: str

    def to_html(self) -> str:
        return escape_telegram_html(self.text)

    def to_plain(self) -> str:
        return self.text
