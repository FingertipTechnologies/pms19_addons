"""PDF rendering of the monthly AMC timesheet report with ReportLab.

Plain module (no Odoo model): ``render_monthly_report_pdf(report)`` builds the
PDF of one ``ft.amc.monthly.report`` record without wkhtmltopdf. It shows the
report header (customer, project, period, total hours) and one row per task
(Date = approval date, Task, Hours of the month's entries as HH:MM) with the
report total hours.
``task_summary_rows(report)`` gives the same rows to the Excel export.

Only plain attribute access and iteration over ``report.line_ids`` are used,
so the renderer can be exercised with simple fake objects.
"""
import base64
import io
import logging
import math
import os
from datetime import date, datetime
from xml.sax.saxutils import escape

import pytz
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_logger = logging.getLogger(__name__)

DATE_FORMAT = '%d/%m/%Y'  # same as the Excel file
DEFAULT_TZ = 'Asia/Kolkata'

# Phone number printed in the PDF footer instead of the company phone
# (contact number to show to AMC customers on the monthly timesheet).


PAGE_SIZE = landscape(A4)
MARGIN_X = 15 * mm
HEADER_HEIGHT = 28 * mm
FOOTER_HEIGHT = 16 * mm
LOGO_MAX_W = 45 * mm
LOGO_MAX_H = 18 * mm

HEADER_BG = colors.HexColor('#D9E1F2')
GRID_COLOR = colors.HexColor('#9AA5B8')
MUTED = colors.HexColor('#555555')

# (regular, bold) TTF candidates, by Odoo resource path or absolute path.
_FONT_CANDIDATES = (
    ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
     '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
    ('/usr/share/fonts/dejavu/DejaVuSans.ttf',
     '/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf'),
    ('/usr/share/fonts/TTF/DejaVuSans.ttf',
     '/usr/share/fonts/TTF/DejaVuSans-Bold.ttf'),
    ('web/static/fonts/google/Open_Sans/Open_Sans-Regular.ttf',
     'web/static/fonts/google/Open_Sans/Open_Sans-Bold.ttf'),
    ('web/static/fonts/lato/Lato-Reg-webfont.ttf',
     'web/static/fonts/lato/Lato-Bol-webfont.ttf'),
    ('web/static/fonts/google/Roboto/Roboto-Regular.ttf',
     'web/static/fonts/google/Roboto/Roboto-Bold.ttf'),
)
_FONT_NAME = 'AmcReportSans'
_FONT_BOLD_NAME = 'AmcReportSans-Bold'
_fonts_cache = None


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _resolve_path(path):
    """Absolute path of ``path`` (absolute or Odoo addon resource), or None."""
    if os.path.isabs(path):
        return path if os.path.isfile(path) else None
    try:
        from odoo.tools.misc import file_path
        return file_path(path)
    except Exception:  # noqa: BLE001 - odoo missing / resource not found
        return None


def _get_fonts():
    """(regular, bold) font names; a Unicode TTF if available, else Helvetica."""
    global _fonts_cache
    if _fonts_cache:
        return _fonts_cache
    fonts = ('Helvetica', 'Helvetica-Bold')
    for regular, bold in _FONT_CANDIDATES:
        regular_path = _resolve_path(regular)
        if not regular_path:
            continue
        bold_path = _resolve_path(bold) or regular_path
        try:
            pdfmetrics.registerFont(TTFont(_FONT_NAME, regular_path))
            pdfmetrics.registerFont(TTFont(_FONT_BOLD_NAME, bold_path))
            pdfmetrics.registerFontFamily(
                _FONT_NAME, normal=_FONT_NAME, bold=_FONT_BOLD_NAME,
                italic=_FONT_NAME, boldItalic=_FONT_BOLD_NAME)
            fonts = (_FONT_NAME, _FONT_BOLD_NAME)
            _logger.debug("AMC report PDF font: %s", regular_path)
            break
        except Exception:  # noqa: BLE001 - unreadable font file, try the next one
            _logger.debug("Cannot register font %s", regular_path, exc_info=True)
    _fonts_cache = fonts
    return fonts


def _translator(report):
    env = getattr(report, 'env', None)
    translate = getattr(env, '_', None)

    def _t(source):
        if translate:
            try:
                return translate(source)
            except Exception:  # noqa: BLE001
                pass
        return source
    return _t


def _txt(value):
    """Record value to text (Odoo uses False for empty values)."""
    if value is None or value is False:
        return ''
    return str(value)


def _para_text(value):
    """Escaped Paragraph markup of ``value`` keeping its line breaks."""
    text = _txt(value).replace('\r\n', '\n').replace('\r', '\n')
    return '<br/>'.join(escape(part) for part in text.split('\n'))


def _to_minutes(hours):
    """Hours (float) to whole minutes, rounded half up to the nearest minute."""
    return int(math.floor((hours or 0.0) * 60 + 0.5))


def _fmt_minutes(minutes):
    """Minutes as HH:MM (e.g. 470 -> 07:50, 7530 -> 125:30)."""
    minutes = int(minutes or 0)
    sign = '-' if minutes < 0 else ''
    hh, mm = divmod(abs(minutes), 60)
    return '%s%02d:%02d' % (sign, hh, mm)


def report_total_minutes(report):
    """Total hours of the report in whole minutes (the shown total)."""
    return _to_minutes(report.total_hours)


def _fmt_date(value):
    if not value:
        return ''
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.strftime(DATE_FORMAT)
    return _txt(value)


def _logo_reader(company):
    """ImageReader of the company logo, or None (missing, SVG, unreadable)."""
    logo = getattr(company, 'logo', False)
    if not logo:
        return None
    try:
        raw = base64.b64decode(logo)
        if raw.lstrip()[:5] in (b'<?xml', b'<svg ') or b'<svg' in raw[:512]:
            return None  # SVG is not supported by ReportLab images
        reader = ImageReader(io.BytesIO(raw))
        reader.getSize()
        return reader
    except Exception:  # noqa: BLE001 - corrupt / unsupported image
        _logger.debug("AMC report PDF: unreadable company logo", exc_info=True)
        return None


def _company_address_lines(company):
    lines = []
    street = ', '.join(filter(None, [_txt(getattr(company, 'street', '')),
                                     _txt(getattr(company, 'street2', ''))]))
    if street:
        lines.append(street)
    state = getattr(company, 'state_id', None)
    country = getattr(company, 'country_id', None)
    city = ' '.join(filter(None, [
        _txt(getattr(company, 'city', '')),
        _txt(getattr(state, 'name', '')) if state else '',
        _txt(getattr(company, 'zip', '')),
    ]))
    if city:
        lines.append(city)
    if country and _txt(getattr(country, 'name', '')):
        lines.append(_txt(country.name))
    return lines


def _company_footer_text(company):
    parts = [
        _txt(getattr(company, 'name', '')),
        _txt(getattr(company, 'email', '')),
         # fixed number, not the company phone
        _txt(getattr(company, 'website', '')),
    ]
    return '  |  '.join(p for p in parts if p)


# ----------------------------------------------------------------------
# page decorations
# ----------------------------------------------------------------------
class _NumberedCanvas(rl_canvas.Canvas):
    """Canvas that draws "Page X of Y" once the page count is known."""

    page_label = 'Page %(page)s of %(total)s'
    font_name = 'Helvetica'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_page_number(total)
            super().showPage()
        super().save()

    def _draw_page_number(self, total):
        width = self._pagesize[0]
        self.saveState()
        self.setFont(self.font_name, 8)
        self.setFillColor(MUTED)
        self.drawRightString(width - MARGIN_X, 8 * mm,
                             self.page_label % {'page': self._pageNumber, 'total': total})
        self.restoreState()


def _make_page_decorator(company, fonts):
    font, font_bold = fonts
    logo = _logo_reader(company)
    company_name = _txt(getattr(company, 'name', ''))
    address = _company_address_lines(company)
    footer_text = _company_footer_text(company)

    def draw(canv, doc):
        width, height = doc.pagesize
        top = height - 10 * mm
        canv.saveState()
        # Header: logo (left), company name and address (right)
        if logo:
            try:
                img_w, img_h = logo.getSize()
                ratio = min(LOGO_MAX_W / img_w, LOGO_MAX_H / img_h)
                draw_w, draw_h = img_w * ratio, img_h * ratio
                canv.drawImage(logo, MARGIN_X, top - draw_h, width=draw_w, height=draw_h,
                               mask='auto', preserveAspectRatio=True)
            except Exception:  # noqa: BLE001
                _logger.debug("AMC report PDF: cannot draw logo", exc_info=True)
        y = top - 4 * mm
        if company_name:
            canv.setFont(font_bold, 11)
            canv.setFillColor(colors.black)
            canv.drawRightString(width - MARGIN_X, y, company_name)
            y -= 4.5 * mm
        canv.setFont(font, 8)
        canv.setFillColor(MUTED)
        for line in address:
            canv.drawRightString(width - MARGIN_X, y, line)
            y -= 3.6 * mm
        line_y = height - HEADER_HEIGHT + 2 * mm
        canv.setStrokeColor(GRID_COLOR)
        canv.setLineWidth(0.6)
        canv.line(MARGIN_X, line_y, width - MARGIN_X, line_y)
        # Footer: company contact details (page number drawn by the canvas)
        canv.line(MARGIN_X, FOOTER_HEIGHT - 3 * mm, width - MARGIN_X, FOOTER_HEIGHT - 3 * mm)
        if footer_text:
            canv.setFont(font, 8)
            canv.setFillColor(MUTED)
            max_w = width - 2 * MARGIN_X - 30 * mm
            text = footer_text
            while text and pdfmetrics.stringWidth(text, font, 8) > max_w:
                text = text[:-2]
            if text != footer_text:
                text = text.rstrip() + '...'
            canv.drawString(MARGIN_X, 8 * mm, text)
        canv.restoreState()

    return draw


# ----------------------------------------------------------------------
# content
# ----------------------------------------------------------------------
def _styles(fonts):
    font, font_bold = fonts
    return {
        'title': ParagraphStyle('amc_title', fontName=font_bold, fontSize=16, leading=20,
                                spaceAfter=4 * mm),
        'h5': ParagraphStyle('amc_h5', fontName=font_bold, fontSize=11, leading=14,
                             spaceBefore=5 * mm, spaceAfter=2 * mm),
        'label': ParagraphStyle('amc_label', fontName=font_bold, fontSize=9, leading=11.5),
        'cell': ParagraphStyle('amc_cell', fontName=font, fontSize=8.5, leading=10.5),
        'cell_bold': ParagraphStyle('amc_cell_bold', fontName=font_bold, fontSize=8.5,
                                    leading=10.5),
        'num': ParagraphStyle('amc_num', fontName=font, fontSize=8.5, leading=10.5,
                              alignment=TA_RIGHT),
        'num_bold': ParagraphStyle('amc_num_bold', fontName=font_bold, fontSize=8.5,
                                   leading=10.5, alignment=TA_RIGHT),
        'th': ParagraphStyle('amc_th', fontName=font_bold, fontSize=8.5, leading=10.5),
        'th_num': ParagraphStyle('amc_th_num', fontName=font_bold, fontSize=8.5, leading=10.5,
                                 alignment=TA_RIGHT),
        'text': ParagraphStyle('amc_text', fontName=font, fontSize=9.5, leading=12),
    }


def _table_style(extra=()):
    return TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HEADER_BG),
        ('GRID', (0, 0), (-1, -1), 0.4, GRID_COLOR),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ] + list(extra))


def _report_tz(report):
    """Company timezone of the report (company contact tz, default Asia/Kolkata)."""
    tz_name = None
    company_tz = getattr(report, '_company_tz', None)
    if callable(company_tz):
        try:
            tz_name = company_tz(report.company_id)
        except Exception:  # noqa: BLE001 - fake objects / missing company
            tz_name = None
    try:
        return pytz.timezone(tz_name or DEFAULT_TZ)
    except pytz.UnknownTimeZoneError:
        return pytz.timezone(DEFAULT_TZ)


def _local_date(value, tz):
    """Local date of a UTC naive datetime (dates are returned unchanged)."""
    if not value:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = pytz.utc.localize(value)
        return value.astimezone(tz).date()
    if isinstance(value, date):
        return value
    return None


def task_summary_rows(report):
    """One dict per task of the report lines, ordered by task name then id.

    Keys: id, name, approved_on (local date or None), hours (sum of that
    task's entries in this report) and minutes (hours rounded to whole
    minutes, shown as HH:MM). Lines without a task are grouped by their task
    name. Used by both the PDF and the Excel file.

    The minutes are balanced so that the rows add up exactly to
    ``report_total_minutes(report)``, the shown total.
    """
    tz = _report_tz(report)
    groups = {}
    for line in report.line_ids:
        task = getattr(line, 'task_id', None)
        task_id = getattr(task, 'id', 0) or 0
        name = _txt(line.task_name) or _txt(getattr(task, 'name', '') if task else '')
        key = ('task', task_id) if task_id else ('name', name)
        row = groups.get(key)
        if row is None:
            row = groups[key] = {
                'id': task_id, 'name': name, 'approved_on': None, 'hours': 0.0,
            }
        row['hours'] += line.hours or 0.0
        row['approved_on'] = row['approved_on'] or _local_date(line.approved_on, tz)
    rows = sorted(groups.values(), key=lambda r: (r['name'].lower(), r['name'], r['id']))
    total = report.total_hours or 0.0
    task_total = sum(r['hours'] for r in rows)
    if abs(task_total - total) >= 0.005:
        _logger.warning(
            "AMC monthly report %s: task hours %.2f differ from total hours %.2f",
            getattr(report, 'id', '?'), task_total, total)
        for row in rows:
            row['minutes'] = _to_minutes(row['hours'])
        return rows
    # Round to whole minutes so that the shown task times add up exactly to
    # the shown total (largest remainder: e.g. 20.4 + 20.4 + 20.2 min -> 20 +
    # 20 + 21 for a 61 min total).
    exact = [row['hours'] * 60 for row in rows]
    floors = [int(math.floor(m + 1e-6)) for m in exact]
    remaining = report_total_minutes(report) - sum(floors)
    order = sorted(range(len(rows)), key=lambda i: (-(exact[i] - floors[i]), i))
    for i in order[:max(remaining, 0)]:
        floors[i] += 1
    for row, value in zip(rows, floors):
        row['minutes'] = value
    return rows


def _build_story(report, fonts, avail_width):
    _t = _translator(report)
    st = _styles(fonts)
    P = Paragraph
    lines = list(report.line_ids)
    story = []

    story.append(P(escape(_t('AMC Timesheet')) + ' - ' + _para_text(report.period_label),
                   st['title']))

    partner = report.partner_id
    project = report.project_id
    info_rows = [
        (_t('Customer'), _txt(getattr(partner, 'display_name', '')) if partner else ''),
        (_t('Project'), _txt(getattr(project, 'name', '')) if project else ''),
        (_t('Reporting month'), _txt(report.period_label)),
        (_t('Period'), '%s - %s' % (_fmt_date(report.period_start),
                                    _fmt_date(report.period_end))),
        (_t('Total hours'), _fmt_minutes(report_total_minutes(report))),
    ]
    info = Table(
        [[P(escape(label), st['label']), P(_para_text(value or '-'), st['text'])]
         for label, value in info_rows],
        colWidths=[40 * mm, avail_width - 40 * mm], hAlign='LEFT')
    info.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 1.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1.5),
    ]))
    story.append(info)
    story.append(Spacer(1, 4 * mm))

    if not lines:
        story.append(P(escape(_t('No approved tasks for this period.')), st['text']))
        return story

    # Tasks: one row per task, hours of this month's entries
    story.append(P(escape(_t('Tasks')), st['h5']))
    task_data = [[
        P(escape(_t('Date')), st['th']),
        P(escape(_t('Task')), st['th']),
        P(escape(_t('Hours')), st['th_num']),
    ]]
    for row in task_summary_rows(report):
        task_data.append([
            P(escape(_fmt_date(row['approved_on'])), st['cell']),
            P(_para_text(row['name']), st['cell']),
            P(_fmt_minutes(row['minutes']), st['num']),
        ])
    task_data.append([
        P(escape(_t('Total hours')), st['num_bold']), '',
        P(_fmt_minutes(report_total_minutes(report)), st['num_bold']),
    ])
    date_w, hours_w = 28 * mm, 25 * mm
    tasks = Table(
        task_data,
        colWidths=[date_w, avail_width - date_w - hours_w, hours_w],
        repeatRows=1, splitInRow=1, hAlign='LEFT')
    tasks.setStyle(_table_style([
        ('SPAN', (0, -1), (1, -1)),
        ('BACKGROUND', (0, -1), (-1, -1), HEADER_BG),
    ]))
    story.append(tasks)
    return story


# ----------------------------------------------------------------------
# public API
# ----------------------------------------------------------------------
def render_monthly_report_pdf(report):
    """PDF (bytes) of one ``ft.amc.monthly.report`` record."""
    fonts = _get_fonts()
    _t = _translator(report)
    company = report.company_id
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=PAGE_SIZE,
        leftMargin=MARGIN_X,
        rightMargin=MARGIN_X,
        topMargin=HEADER_HEIGHT + 2 * mm,
        bottomMargin=FOOTER_HEIGHT,
        title=_txt(report.name),
        author=_txt(getattr(company, 'name', '')),
        subject=_txt(report.period_label),
    )
    story = _build_story(report, fonts, doc.width)
    decorate = _make_page_decorator(company, fonts)

    page_label = _t('Page %(page)s of %(total)s')
    if '%(page)s' not in page_label or '%(total)s' not in page_label:
        page_label = 'Page %(page)s of %(total)s'
    canvas_class = type('AmcNumberedCanvas', (_NumberedCanvas,), {
        'page_label': page_label,
        'font_name': fonts[0],
    })
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate, canvasmaker=canvas_class)
    return buffer.getvalue()
