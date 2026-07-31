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
from src.ux.speaker_label import humanize_speaker_label

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
    ``intro`` — необязательная вводная строка под заголовком: одним предложением
    объясняет новичку, зачем шаг (задаёт её вызывающий только в главном виде).
    ``hint`` — необязательная строка-следствие внизу карточки (nudge о том, что
    неназванные спикеры уйдут метками); задаёт её вызывающий, только когда есть
    несопоставленные спикеры. Пустые вводная и подсказка строк не добавляют.
    ``record_name`` — имя записи, к которой относится карточка: без него две
    карточки в чате неразличимы, а вопрос «кто есть кто» задан о неизвестно чём
    (критика v11).
    """

    header: str
    rows: tuple[SpeakerRow, ...] = ()
    hint: Optional[str] = None
    intro: Optional[str] = None
    record_name: Optional[str] = None

    def to_html(self) -> str:
        """Разметка Telegram HTML: жирные заголовок и спикеры, цитаты в кавычках."""
        lines = [f"<b>{escape_telegram_html(self.header)}</b>"]
        if self.record_name:
            lines.append(escape_telegram_html(self.record_name))
        if self.intro:
            lines.append(escape_telegram_html(self.intro))
        lines.append("")
        for row in self.rows:
            label = humanize_speaker_label(row.speaker_id)
            speaker = f"<b>{escape_telegram_html(label)}</b>"
            if row.display_name:
                lines.append(f"{speaker} → {escape_telegram_html(row.display_name)} ✓")
            else:
                lines.append(f"{speaker} → {escape_telegram_html(_NOT_DEFINED)} ❓")
            if row.quote:
                lines.append(f'  "{escape_telegram_html(row.quote)}"')
            lines.append("")
        if self.hint:
            lines.append(f"<i>{escape_telegram_html(self.hint)}</i>")
        return "\n".join(lines).rstrip("\n")

    def to_plain(self) -> str:
        """Plain-страховка: то же содержимое без тегов и без экранирования."""
        lines = [self.header]
        if self.record_name:
            lines.append(self.record_name)
        if self.intro:
            lines.append(self.intro)
        lines.append("")
        for row in self.rows:
            label = humanize_speaker_label(row.speaker_id)
            if row.display_name:
                lines.append(f"{label} → {row.display_name} ✓")
            else:
                lines.append(f"{label} → {_NOT_DEFINED} ❓")
            if row.quote:
                lines.append(f'  "{row.quote}"')
            lines.append("")
        if self.hint:
            lines.append(self.hint)
        return "\n".join(lines).rstrip("\n")


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
