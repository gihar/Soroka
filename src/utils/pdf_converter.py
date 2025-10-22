"""
Утилита для конвертации Markdown в PDF с поддержкой кириллицы
"""

import re
import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


def convert_markdown_to_pdf(markdown_text: str, output_path: str) -> None:
    """
    Конвертирует markdown текст в PDF файл с поддержкой кириллицы
    
    Args:
        markdown_text: текст в формате markdown
        output_path: путь к выходному PDF файлу
    """
    # Регистрируем шрифты с поддержкой кириллицы
    # Ищем системные шрифты
    font_registered = False
    
    # Попробуем найти и зарегистрировать системные шрифты для macOS
    possible_fonts = [
        # macOS
        '/System/Library/Fonts/Helvetica.ttc',
        '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
        '/Library/Fonts/Arial Unicode.ttf',
        # Linux
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
    ]
    
    for font_path in possible_fonts:
        if os.path.exists(font_path):
            try:
                if font_path.endswith('.ttc'):
                    # TrueType Collection - используем первый шрифт
                    pdfmetrics.registerFont(TTFont('CustomFont', font_path, subfontIndex=0))
                    pdfmetrics.registerFont(TTFont('CustomFont-Bold', font_path, subfontIndex=1))
                else:
                    pdfmetrics.registerFont(TTFont('CustomFont', font_path))
                    pdfmetrics.registerFont(TTFont('CustomFont-Bold', font_path))
                font_registered = True
                break
            except Exception:
                continue
    
    # Если не нашли системный шрифт, используем стандартный Helvetica
    font_name = 'CustomFont' if font_registered else 'Helvetica'
    font_name_bold = 'CustomFont-Bold' if font_registered else 'Helvetica-Bold'
    
    # Создаем PDF документ
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )
    
    # Стили с кастомными шрифтами
    styles = getSampleStyleSheet()
    
    # Кастомные стили с поддержкой кириллицы
    styles.add(ParagraphStyle(
        name='CustomTitle',
        fontName=font_name_bold,
        fontSize=24,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=12,
        spaceBefore=12,
        leading=28
    ))
    
    styles.add(ParagraphStyle(
        name='CustomHeading2',
        fontName=font_name_bold,
        fontSize=18,
        textColor=colors.HexColor('#34495e'),
        spaceAfter=10,
        spaceBefore=10,
        leading=22
    ))
    
    styles.add(ParagraphStyle(
        name='CustomHeading3',
        fontName=font_name_bold,
        fontSize=14,
        textColor=colors.HexColor('#7f8c8d'),
        spaceAfter=8,
        spaceBefore=8,
        leading=18
    ))
    
    styles.add(ParagraphStyle(
        name='CustomBody',
        fontName=font_name,
        fontSize=12,
        leading=16,
        alignment=TA_LEFT
    ))
    
    # Парсинг markdown и создание элементов
    story = []
    lines = markdown_text.split('\n')
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # Пропускаем пустые строки
        if not line:
            story.append(Spacer(1, 0.3*cm))
            i += 1
            continue
        
        # Заголовки
        if line.startswith('# '):
            text = line[2:].strip()
            story.append(Paragraph(text, styles['CustomTitle']))
        elif line.startswith('## '):
            text = line[3:].strip()
            story.append(Paragraph(text, styles['CustomHeading2']))
        elif line.startswith('### '):
            text = line[4:].strip()
            story.append(Paragraph(text, styles['CustomHeading3']))
        
        # Списки
        elif line.startswith('- ') or line.startswith('* '):
            text = '• ' + line[2:].strip()
            # Обрабатываем жирный текст в списках
            text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
            text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
            story.append(Paragraph(text, styles['CustomBody']))
        elif re.match(r'^\d+\.\s', line):
            text = line
            # Обрабатываем жирный текст в нумерованных списках
            text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
            text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
            story.append(Paragraph(text, styles['CustomBody']))
        
        # Обычный текст
        else:
            # Обрабатываем жирный текст **text**
            text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', line)
            # Обрабатываем курсив *text*
            text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
            story.append(Paragraph(text, styles['CustomBody']))
        
        i += 1
    
    # Генерируем PDF
    doc.build(story)

