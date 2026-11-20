# -*- coding: utf-8 -*-
"""Date bucketing for the daily / weekly / monthly summary report.  Pure Python."""
from datetime import timedelta

GRANULARITIES = ('day', 'week', 'month')


def bucket_start(day, granularity):
    """First day of the bucket containing ``day`` (weeks start on Monday)."""
    if granularity == 'week':
        return day - timedelta(days=day.weekday())
    if granularity == 'month':
        return day.replace(day=1)
    return day


def next_bucket(start, granularity):
    if granularity == 'week':
        return start + timedelta(days=7)
    if granularity == 'month':
        return (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start + timedelta(days=1)


def iter_buckets(start, end, granularity):
    """Every bucket start from the one containing ``start`` up to ``end``."""
    current = bucket_start(start, granularity)
    while current <= end:
        yield current
        current = next_bucket(current, granularity)


def bucket_label(start, granularity):
    if granularity == 'week':
        iso = start.isocalendar()
        return 'W%02d %s' % (iso[1], start.isoformat())
    if granularity == 'month':
        return start.strftime('%Y-%m')
    return start.isoformat()


# ---------------------------------------------------------------- comparison + formatting (PDF and screen share the rules)
def pct_change(current, previous):
    """Whole-number % change; None when undefined (previous is 0 and current is not)."""
    current, previous = float(current or 0), float(previous or 0)
    if previous == 0:
        return 0 if current == 0 else None
    return int(round((current - previous) / abs(previous) * 100))


def change_text(current, previous, has_previous):
    """Text of the "change vs previous" cell, e.g. '-93%', '+20%', 'new', '—'."""
    if not has_previous:
        return '\u2014'
    change = pct_change(current, previous)
    if change is None:
        return 'new'
    if change == 0:
        return '0%'
    return '%+d%%' % change


def comparison_rows(rows, key='field_edits'):
    """Newest first; every row compared with the chronologically previous one.
    ``rows`` must be in chronological order and already without empty periods."""
    out = []
    for i, row in enumerate(rows):
        previous = rows[i - 1][key] if i else 0
        out.append(dict(row, change=change_text(row[key], previous, i > 0)))
    return list(reversed(out))


def fmt_num(value, decimals=None):
    """1234567 -> '1,234,567'; floats keep one decimal unless ``decimals`` says otherwise."""
    if value is None or value is False:
        return ''
    number = float(value)
    if decimals is None:
        decimals = 0 if number == int(number) else 1
    return '{:,.{d}f}'.format(number, d=decimals)


def share_of_top(value, top):
    top = float(top or 0)
    if top <= 0:
        return 0
    return max(0, min(100, int(round(float(value or 0) / top * 100))))
