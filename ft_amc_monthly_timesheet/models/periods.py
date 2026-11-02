"""Calendar-month helpers for AMC reporting.

Pure Python (no Odoo import) so they can be unit-tested standalone.
"""
from datetime import date, datetime, time, timedelta

import pytz


def month_start(value):
    """First day of the month of ``value``."""
    return value.replace(day=1)


def month_end(value):
    """Last day of the month of ``value``."""
    first_next = date(value.year + (value.month == 12), value.month % 12 + 1, 1)
    return first_next - timedelta(days=1)


def previous_month(today):
    """(first day, last day) of the calendar month before ``today``."""
    end = month_start(today) - timedelta(days=1)
    return month_start(end), end


def local_bounds_utc(start, end, tzname):
    """UTC naive datetimes bounding the local days ``start``..``end``.

    Returns ``(start 00:00 local, (end + 1 day) 00:00 local)`` converted to UTC
    without tzinfo, i.e. a half-open interval usable on Datetime fields:
    ``field >= lower and field < upper``.
    """
    tz = pytz.timezone(tzname or 'UTC')

    def to_utc(day):
        local = tz.localize(datetime.combine(day, time.min))
        return local.astimezone(pytz.utc).replace(tzinfo=None)

    return to_utc(start), to_utc(end + timedelta(days=1))
