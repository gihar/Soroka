"""
PDF converter with corporate minimalist styling.
Converts Markdown protocol text to a professional business-style PDF.
"""

import os
import re
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    PageTemplate,
    Paragraph,
    Spacer,
)

# --- Color palette (corporate minimalist) ---
COLOR_PRIMARY = colors.HexColor('#1a1a2e')    # near-black for titles
COLOR_SECONDARY = colors.HexColor('#2c3e50')  # dark slate for headings
COLOR_MUTED = colors.HexColor('#7f8c8d')      # grey for meta/footer
COLOR_RULE = colors.HexColor('#bdc3c7')        # light grey for lines
COLOR_BODY = colors.HexColor('#2d2d2d')        # soft black for body


def _font_candidates():
    """Пути к кириллическим шрифтам: системные + переносимый DejaVu из venv."""
    candidates = [
        '/System/Library/Fonts/Helvetica.ttc',
        '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
        '/Library/Fonts/Arial Unicode.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
    ]
    try:
        import matplotlib
        candidates.append(
            os.path.join(matplotlib.get_data_path(), 'fonts', 'ttf', 'DejaVuSans.ttf')
        )
    except Exception:
        pass
    return candidates


def _register_fonts():
    """Register system Cyrillic fonts. Returns (regular, bold) font names."""
    from loguru import logger

    for path in _font_candidates():
        if not os.path.exists(path):
            continue
        try:
            if path.endswith('.ttc'):
                pdfmetrics.registerFont(TTFont('SorokaFont', path, subfontIndex=0))
                pdfmetrics.registerFont(TTFont('SorokaFont-Bold', path, subfontIndex=1))
            else:
                pdfmetrics.registerFont(TTFont('SorokaFont', path))
                pdfmetrics.registerFont(TTFont('SorokaFont-Bold', path))
            return 'SorokaFont', 'SorokaFont-Bold'
        except Exception as exc:
            logger.warning(f"Could not register font from {path}: {exc}")
            continue

    logger.error(
        "Кириллический шрифт не найден — PDF будет с битой кириллицей (Helvetica). "
        "Установите dejavu/liberation шрифты на сервере."
    )
    return 'Helvetica', 'Helvetica-Bold'


# Register fonts once at module load
_FONT_REGULAR, _FONT_BOLD = _register_fonts()


def _build_styles(font, font_bold):
    """Create all paragraph styles for the document."""
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name='DocTitle',
        fontName=font_bold,
        fontSize=22,
        textColor=COLOR_PRIMARY,
        spaceBefore=6,
        spaceAfter=4,
        leading=26,
    ))

    styles.add(ParagraphStyle(
        name='Section',
        fontName=font_bold,
        fontSize=13,
        textColor=COLOR_SECONDARY,
        spaceBefore=14,
        spaceAfter=6,
        leading=17,
    ))

    styles.add(ParagraphStyle(
        name='SubSection',
        fontName=font_bold,
        fontSize=11,
        textColor=COLOR_MUTED,
        spaceBefore=10,
        spaceAfter=4,
        leading=15,
    ))

    styles.add(ParagraphStyle(
        name='Body',
        fontName=font,
        fontSize=10,
        textColor=COLOR_BODY,
        leading=15,
        spaceBefore=1,
        spaceAfter=1,
        alignment=TA_LEFT,
    ))

    styles.add(ParagraphStyle(
        name='BulletItem',
        fontName=font,
        fontSize=10,
        textColor=COLOR_BODY,
        leading=15,
        leftIndent=12,
        spaceBefore=1,
        spaceAfter=1,
    ))

    # Нумерованные пункты — с тем же отступом, что и маркированные:
    # «1. …» не должен сливаться с обычными абзацами.
    styles.add(ParagraphStyle(
        name='NumberItem',
        fontName=font,
        fontSize=10,
        textColor=COLOR_BODY,
        leading=15,
        leftIndent=12,
        spaceBefore=1,
        spaceAfter=1,
    ))

    return styles


def _make_header_footer(font, font_bold):
    """Create header/footer callback bound to the registered Cyrillic fonts."""
    today = datetime.now().strftime('%d.%m.%Y')  # captured once per document

    def _draw(canvas, doc):
        canvas.saveState()
        width, height = A4

        # --- Header line ---
        y_header = height - 1.4 * cm
        canvas.setStrokeColor(COLOR_RULE)
        canvas.setLineWidth(0.5)
        canvas.line(2 * cm, y_header, width - 2 * cm, y_header)

        # Колонтитул без бренда генератора: протокол — документ владельца
        # встречи, слева пусто, справа номер страницы.
        canvas.setFont(font_bold, 8)
        canvas.setFillColor(COLOR_MUTED)
        canvas.drawRightString(
            width - 2 * cm, y_header + 3 * mm,
            f'стр. {doc.page}'
        )

        # --- Footer line ---
        y_footer = 1.4 * cm
        canvas.setStrokeColor(COLOR_RULE)
        canvas.line(2 * cm, y_footer, width - 2 * cm, y_footer)

        canvas.setFont(font, 7)
        canvas.setFillColor(COLOR_MUTED)
        canvas.drawString(2 * cm, y_footer - 3 * mm, today)

        canvas.restoreState()

    return _draw


def _section_rule():
    """Thin horizontal rule before H2 sections."""
    return HRFlowable(
        width='100%',
        thickness=0.5,
        color=COLOR_RULE,
        spaceBefore=10,
        spaceAfter=4,
    )


def _is_horizontal_rule(stripped_line: str) -> bool:
    """Строка-линейка Markdown (---): в PDF это линия, а не текст «---»."""
    return bool(re.match(r'^-{3,}$', stripped_line))


# Диапазоны ниже U+2600 добавлены выборочно (‼ ℹ стрелки ⌚–⏺ ▪–◾ ⬅–⭕ ⤴⤵),
# чтобы не задеть типографику: тире U+2013/2014, буллет U+2022, № U+2116, … U+2026.
_EMOJI_RUN = (
    r"[‼⁉ℹ↔-↪⌚-⏺Ⓜ▪-◾"
    r"⤴⤵⬅-⭕☀-➿\U0001F000-\U0001FAFF️]+"
)
# Эмодзи после начала строки, пробела или ** снимается вместе с хвостовым
# пробелом, чтобы не оставлять дыр («**👥 Участники:**» → «**Участники:**»).
_EMOJI_AT_BOUNDARY_RE = re.compile(rf"(^|\s|\*\*){_EMOJI_RUN}\s?")
_EMOJI_ANYWHERE_RE = re.compile(_EMOJI_RUN)


def strip_emoji(text: str) -> str:
    """Снять эмодзи из текста PDF: глифов в TTF-шрифтах нет, вместо них — тофу."""
    without_boundary = _EMOJI_AT_BOUNDARY_RE.sub(r"\1", text)
    return _EMOJI_ANYWHERE_RE.sub("", without_boundary).strip()


def _format_inline(text):
    """Escape XML special chars, then convert markdown inline markup to ReportLab tags.

    Согласовано с чат-рендером (protocol_render.telegram_html): **жирный** и
    `код`; одиночные звёздочки остаются буквальным текстом.
    """
    from xml.sax.saxutils import escape
    safe = escape(strip_emoji(text))  # & → &amp;  < → &lt;  > → &gt;
    safe = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', safe)
    safe = re.sub(r'`([^`]+)`', r'<font face="Courier">\1</font>', safe)
    return safe


def _markdown_to_story(markdown_text: str, styles) -> list:
    """Разобрать Markdown протокола в список флоу-элементов ReportLab.

    Пустая строка даёт вертикальный отступ, но подряд идущие пустые строки
    (частый след пустых ``{% if %}``-секций) не копят Spacer друг на друга —
    иначе в PDF появляются вертикальные дыры.
    """
    story: list = []
    first_heading_seen = False

    for line in markdown_text.split('\n'):
        stripped = line.strip()

        # Empty line → small spacer, но не стопкой: подряд идущие пустые строки
        # схлопываются в один отступ.
        if not stripped:
            if not (story and isinstance(story[-1], Spacer)):
                story.append(Spacer(1, 2 * mm))
            continue

        # Headings: check most-specific first (#### before ### before ## before #)
        if stripped.startswith('#### '):
            story.append(Paragraph(_format_inline(stripped[5:].strip()), styles['SubSection']))

        elif stripped.startswith('### '):
            story.append(Paragraph(_format_inline(stripped[4:].strip()), styles['SubSection']))

        elif stripped.startswith('## '):
            if first_heading_seen:
                story.append(_section_rule())
            story.append(Paragraph(_format_inline(stripped[3:].strip()), styles['Section']))
            first_heading_seen = True

        elif stripped.startswith('# '):
            story.append(Paragraph(_format_inline(stripped[2:].strip()), styles['DocTitle']))
            first_heading_seen = True

        # Horizontal rule (---) → section line, not literal dashes
        elif _is_horizontal_rule(stripped):
            story.append(_section_rule())

        # Bullet list
        elif stripped.startswith('- ') or stripped.startswith('* '):
            text = stripped[2:].strip()
            story.append(Paragraph(
                f'<bullet>&bull;</bullet>{_format_inline(text)}',
                styles['BulletItem'],
            ))

        # Numbered list
        elif re.match(r'^\d+\.\s', stripped):
            story.append(Paragraph(_format_inline(stripped), styles['NumberItem']))

        # Regular text
        else:
            story.append(Paragraph(_format_inline(stripped), styles['Body']))

    return story


def convert_markdown_to_pdf(markdown_text: str, output_path: str) -> None:
    """
    Convert markdown protocol text to a professional business-style PDF.

    Args:
        markdown_text: protocol text in markdown format
        output_path: path to the output PDF file
    """
    font, font_bold = _FONT_REGULAR, _FONT_BOLD
    styles = _build_styles(font, font_bold)

    # Document with header/footer
    doc = BaseDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2.2 * cm,
        bottomMargin=2.2 * cm,
    )

    frame = Frame(
        doc.leftMargin, doc.bottomMargin,
        doc.width, doc.height,
        id='main',
    )

    doc.addPageTemplates([
        PageTemplate(id='default', frames=frame, onPage=_make_header_footer(font, font_bold)),
    ])

    story = _markdown_to_story(markdown_text, styles)
    doc.build(story)


async def convert_markdown_to_pdf_async(markdown_text: str, output_path: str) -> None:
    """Async wrapper — runs PDF generation in thread pool to avoid blocking event loop."""
    from src.performance.async_optimization import thread_manager
    await thread_manager.run_in_thread(convert_markdown_to_pdf, markdown_text, output_path)
