"""Monday-to-Sunday helpers shared by the Week model and project.task.

A Week always runs Monday -> Sunday. Every date the module stores or compares
is derived here so the rule lives in one place: the week a day belongs to, the
Sunday that closes it, and the UTC bounds of a local calendar day.
"""
from datetime import date, datetime, time, timedelta

import pytz

WEEK_LENGTH = 7

# Week 1: the Monday that opens ISO week 1 of 2026.
#
# Weeks are counted straight on from here instead of restarting every January,
# so W53 (the last week of 2026) is followed by W54 in January 2027 rather than
# by W1 again — the number alone identifies a week and no year has to be
# carried beside it.
#
# A fixed point on purpose. Anchoring on the data instead (the earliest week on
# file, say) would renumber every week in the database the first time somebody
# back-dated a task.
WEEK_EPOCH = date(2025, 12, 29)


def monday_of(day):
    """The Monday that opens the week containing ``day``."""
    return day - timedelta(days=day.weekday())


def week_number(day):
    """The continuous week number of the week containing ``day``.

    1 for the week of :data:`WEEK_EPOCH`, and one more for every week since — so
    the count runs on through the turn of the year: the last week of 2026 is
    W53 and the first of 2027 is W54.

    Zero and below for anything before the epoch, which is why callers should
    reach for :func:`week_label` rather than this.
    """
    return ((monday_of(day) - WEEK_EPOCH).days // WEEK_LENGTH) + 1


def week_label(day):
    """What a week is called: "W25", or "W40 2025" from before the count began.

    The continuous count starts at the first week of 2026, so weeks earlier
    than that have no number in it — the arithmetic gives them zero and
    negatives, and a row reading "W-12" says nothing to anybody. They keep the
    ISO name they had, year included, which reads as what it is: a week from
    before the numbering started.

    That leaves two formats in one list, and it is the lesser problem. The
    alternative was renumbering the count so that 2025 fitted into it, which is
    exactly what the numbering was changed away from.
    """
    number = week_number(day)
    if number >= 1:
        return 'W%s' % number
    iso_year, iso_week, _weekday = day.isocalendar()
    return 'W%s %s' % (iso_week, iso_year)


def sunday_of(day):
    """The Sunday that closes the week containing ``day``."""
    return monday_of(day) + timedelta(days=WEEK_LENGTH - 1)


def local_day_bounds(env, day, end_of_day=False):
    """Naive UTC datetime for the start (or the end) of a local calendar day.

    ``date_deadline`` is a Datetime stored in UTC, while a Week is expressed in
    calendar dates. Comparing the two straight off the column buckets work by
    the UTC day, which is the wrong day for anything late in the local evening
    (23:00 IST is already tomorrow in UTC). Converting the day's local bounds
    to UTC first puts both sides on the user's calendar.
    """
    tz = pytz.timezone(env.context.get('tz') or env.user.tz or 'UTC')
    moment = time(23, 59, 59) if end_of_day else time.min
    return tz.localize(datetime.combine(day, moment)).astimezone(
        pytz.utc).replace(tzinfo=None)


def hours_to_hhmm(hours):
    """0.5 -> "00:30". What the float_time widget shows everywhere else.

    The task boards are drawn from plain JSON rather than from field values, so
    they have no widget to do this for them; formatting here keeps the cards
    reading the same as the hour totals beside them.
    """
    sign = '-' if hours < 0 else ''
    minutes = int(round(abs(hours) * 60))
    return '%s%02d:%02d' % (sign, minutes // 60, minutes % 60)
