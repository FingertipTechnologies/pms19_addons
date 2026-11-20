# -*- coding: utf-8 -*-
"""Pure unit tests (no database): payload validation and heartbeat maths."""
from datetime import datetime, timedelta

from odoo.tests.common import BaseCase, tagged

from odoo.addons.adoption_intelligence.services import payload_validation as pv
from odoo.addons.adoption_intelligence.services import session_math as sm

NOW_MS = 1_800_000_000_000
KEY = 'abcdef123456'


@tagged('post_install', '-at_install', 'adoption_pure')
class TestPayloadValidation(BaseCase):

    def _visit(self, **kw):
        base = {'t': 'visit', 'key': KEY, 'ev': 'record_view', 'kind': 'record',
                'model': 'crm.lead', 'rid': 125, 'ts': NOW_MS}
        base.update(kw)
        return base

    def test_valid_visit(self):
        ev, why = pv.validate_event(self._visit(), NOW_MS)
        self.assertIsNone(why)
        self.assertEqual((ev['model'], ev['record_id'], ev['event_type']),
                         ('crm.lead', 125, 'record_view'))

    def test_user_id_in_payload_is_ignored(self):
        ev, _ = pv.validate_event(self._visit(uid=2, user_id=2), NOW_MS)
        self.assertNotIn('uid', ev)
        self.assertNotIn('user_id', ev)

    def test_rejects_bad_keys_types_and_models(self):
        for bad in (self._visit(key='short'), self._visit(key='a b c d e f g h'),
                    self._visit(key=None), self._visit(ev='hack'),
                    self._visit(model='crm.lead; drop table x'),
                    {'t': 'nope', 'key': KEY}, 'string', None, 5):
            ev, why = pv.validate_event(bad, NOW_MS)
            self.assertIsNone(ev, bad)
            self.assertTrue(why)

    def test_client_clock_is_not_trusted(self):
        self.assertEqual(pv.resolve_event_ms(NOW_MS - 10_000, NOW_MS), NOW_MS - 10_000)
        self.assertEqual(pv.resolve_event_ms(NOW_MS + 3_600_000, NOW_MS), NOW_MS)       # future
        self.assertEqual(pv.resolve_event_ms(NOW_MS - 3 * 86_400_000, NOW_MS), NOW_MS)  # too old
        self.assertEqual(pv.resolve_event_ms('garbage', NOW_MS), NOW_MS)

    def test_beat_clamps_and_validates(self):
        ev, _ = pv.validate_event({'t': 'beat', 'key': KEY, 'seq': 3, 'act': 999, 'ela': 100}, NOW_MS)
        self.assertEqual(ev['active_s'], 100)        # active <= elapsed
        ev, _ = pv.validate_event({'t': 'beat', 'key': KEY, 'seq': 1, 'act': 1, 'ela': 10 ** 9}, NOW_MS)
        self.assertEqual(ev['elapsed_s'], pv.MAX_SECONDS)
        ev, why = pv.validate_event({'t': 'beat', 'key': KEY, 'seq': 'x', 'act': 1, 'ela': 1}, NOW_MS)
        self.assertIsNone(ev)

    def test_payload_limits_and_duplicates(self):
        events = [self._visit(key='k%011d' % i) for i in range(pv.MAX_EVENTS_PER_REQUEST + 1)]
        _, _, err = pv.validate_payload({'events': events}, NOW_MS)
        self.assertEqual(err, 'too_many_events')
        _, _, err = pv.validate_payload({'events': 'x'}, NOW_MS)
        self.assertEqual(err, 'bad_payload')
        beat = {'t': 'beat', 'key': KEY, 'seq': 1, 'act': 5, 'ela': 10}
        clean, rejected, err = pv.validate_payload({'events': [beat, dict(beat)]}, NOW_MS)
        self.assertEqual((len(clean), rejected, err), (1, 1, None))


@tagged('post_install', '-at_install', 'adoption_pure')
class TestSessionMath(BaseCase):

    def setUp(self):
        super().setUp()
        self.t0 = datetime(2026, 10, 20, 9, 0, 0)
        self.state = {'started_at': self.t0, 'elapsed_seconds': 0, 'active_seconds': 0,
                      'heartbeat_count': 0, 'last_seq': -1, 'state': 'open'}

    def beat(self, seq, act, ela, end=False):
        return {'seq': seq, 'active_s': act, 'elapsed_s': ela, 'ended': end}

    def test_elapsed_and_active(self):
        s = sm.merge_beat(self.state, self.beat(1, 25, 30), self.t0 + timedelta(seconds=30))
        self.assertEqual((s['elapsed_seconds'], s['active_seconds']), (30, 25))
        self.assertEqual(sm.idle_seconds(s['elapsed_seconds'], s['active_seconds']), 5)

    def test_idle_time_is_not_credited(self):
        # 10 minutes on the page but only 40s of real interaction
        s = sm.merge_beat(self.state, self.beat(1, 40, 600), self.t0 + timedelta(seconds=600))
        self.assertEqual(s['active_seconds'], 40)
        self.assertEqual(sm.idle_seconds(s['elapsed_seconds'], s['active_seconds']), 560)

    def test_duplicate_heartbeat_is_idempotent(self):
        now = self.t0 + timedelta(seconds=30)
        once = sm.merge_beat(self.state, self.beat(1, 25, 30), now)
        twice = sm.merge_beat(once, self.beat(1, 25, 30), now + timedelta(seconds=1))
        self.assertEqual(once['active_seconds'], twice['active_seconds'])
        self.assertEqual(once['elapsed_seconds'], twice['elapsed_seconds'])
        self.assertEqual(twice['heartbeat_count'], 1)

    def test_out_of_order_heartbeat_cannot_go_backwards(self):
        a = sm.merge_beat(self.state, self.beat(2, 50, 60), self.t0 + timedelta(seconds=60))
        b = sm.merge_beat(a, self.beat(1, 20, 30), self.t0 + timedelta(seconds=61))
        self.assertEqual(b['active_seconds'], 50)
        self.assertEqual(b['last_seq'], 2)

    def test_client_cannot_claim_more_time_than_server_clock_allows(self):
        s = sm.merge_beat(self.state, self.beat(1, 80000, 86400), self.t0 + timedelta(seconds=30))
        self.assertLessEqual(s['elapsed_seconds'], 30 + sm.GRACE_SECONDS)
        self.assertLessEqual(s['active_seconds'], s['elapsed_seconds'])

    def test_close_and_stale(self):
        s = sm.merge_beat(self.state, self.beat(1, 5, 10, end=True), self.t0 + timedelta(seconds=10))
        self.assertEqual(s['state'], 'closed')
        self.assertTrue(sm.is_stale(self.t0, self.t0 + timedelta(minutes=11), 10))
        self.assertFalse(sm.is_stale(self.t0, self.t0 + timedelta(minutes=5), 10))

    def test_closed_session_is_not_reopened_by_late_duplicate(self):
        closed = sm.merge_beat(self.state, self.beat(1, 5, 10, end=True), self.t0 + timedelta(seconds=10))
        late = sm.merge_beat(closed, self.beat(1, 5, 10), self.t0 + timedelta(seconds=20))
        self.assertEqual(late['state'], 'closed')


@tagged('post_install', '-at_install', 'adoption_pure')
class TestRateLimiter(BaseCase):

    def test_budget_and_window(self):
        clock = {'t': 0.0}
        lim = pv.SlidingWindowLimiter(max_events=10, window_seconds=60, clock=lambda: clock['t'])
        self.assertTrue(lim.allow('u1', 6))
        self.assertFalse(lim.allow('u1', 5))          # would exceed the budget
        self.assertTrue(lim.allow('u2', 10))          # other users unaffected
        clock['t'] = 61.0
        self.assertTrue(lim.allow('u1', 10))          # window slid


@tagged('post_install', '-at_install', 'adoption_pure')
class TestReportBuckets(BaseCase):
    """Daily / weekly / monthly bucketing used by the Reports screen."""

    def setUp(self):
        super().setUp()
        from odoo.addons.adoption_intelligence.services import report_utils
        self.ru = report_utils

    def test_week_starts_on_monday(self):
        from datetime import date
        self.assertEqual(self.ru.bucket_start(date(2026, 10, 21), 'week'), date(2026, 10, 19))   # Wednesday
        self.assertEqual(self.ru.bucket_start(date(2026, 10, 19), 'week'), date(2026, 10, 19))   # Monday
        self.assertEqual(self.ru.bucket_start(date(2026, 10, 25), 'week'), date(2026, 10, 19))   # Sunday

    def test_month_and_day(self):
        from datetime import date
        self.assertEqual(self.ru.bucket_start(date(2026, 10, 21), 'month'), date(2026, 10, 1))
        self.assertEqual(self.ru.bucket_start(date(2026, 10, 21), 'day'), date(2026, 10, 21))

    def test_iteration_has_no_gaps_or_duplicates(self):
        from datetime import date
        days = list(self.ru.iter_buckets(date(2026, 10, 1), date(2026, 10, 10), 'day'))
        self.assertEqual(len(days), 10)
        weeks = list(self.ru.iter_buckets(date(2026, 10, 1), date(2026, 10, 31), 'week'))
        self.assertEqual(weeks[0], date(2026, 9, 28))                     # week containing 1 Oct
        self.assertTrue(all((b - a).days == 7 for a, b in zip(weeks, weeks[1:])))
        months = list(self.ru.iter_buckets(date(2026, 11, 15), date(2027, 2, 3), 'month'))
        self.assertEqual(months, [date(2026, 11, 1), date(2026, 12, 1), date(2027, 1, 1), date(2027, 2, 1)])

    def test_year_end_rollover_and_labels(self):
        from datetime import date
        self.assertEqual(self.ru.next_bucket(date(2026, 12, 1), 'month'), date(2027, 1, 1))
        self.assertEqual(self.ru.next_bucket(date(2026, 1, 31), 'month') if False else self.ru.next_bucket(date(2026, 1, 1), 'month'), date(2026, 2, 1))
        self.assertEqual(self.ru.bucket_label(date(2026, 10, 1), 'month'), '2026-10')
        self.assertEqual(self.ru.bucket_label(date(2026, 10, 19), 'day'), '2026-10-19')
        self.assertTrue(self.ru.bucket_label(date(2026, 10, 19), 'week').startswith('W43 2026-10-19'))

    def test_every_day_falls_in_exactly_one_bucket(self):
        from datetime import date, timedelta
        start, end = date(2026, 2, 20), date(2026, 4, 10)
        for gran in ('day', 'week', 'month'):
            buckets = set(self.ru.iter_buckets(start, end, gran))
            d = start
            while d <= end:
                self.assertIn(self.ru.bucket_start(d, gran), buckets, (gran, d))
                d += timedelta(days=1)


@tagged('post_install', '-at_install', 'adoption_pure')
class TestReportComparison(BaseCase):
    """The PDF and the on-screen table use the same rules (mirrors adoption_chart_math.js)."""

    def setUp(self):
        super().setUp()
        from odoo.addons.adoption_intelligence.services import report_utils
        self.ru = report_utils

    def test_screenshot_case_54_to_4_is_minus_93(self):
        self.assertEqual(self.ru.pct_change(4, 54), -93)
        self.assertEqual(self.ru.change_text(4, 54, True), '-93%')
        self.assertEqual(self.ru.change_text(60, 50, True), '+20%')

    def test_no_division_by_zero(self):
        self.assertIsNone(self.ru.pct_change(5, 0))
        self.assertEqual(self.ru.pct_change(0, 0), 0)
        self.assertEqual(self.ru.change_text(3, 0, True), 'new')
        self.assertEqual(self.ru.change_text(9, 0, False), '\u2014')
        self.assertEqual(self.ru.change_text(5, 5, True), '0%')

    def test_comparison_rows_newest_first_with_first_period_blank(self):
        rows = [{'label': 'Sep 2026', 'field_edits': 54}, {'label': 'Oct 2026', 'field_edits': 4}]
        out = self.ru.comparison_rows(rows)
        self.assertEqual([r['label'] for r in out], ['Oct 2026', 'Sep 2026'])
        self.assertEqual([r['change'] for r in out], ['-93%', '\u2014'])
        self.assertEqual(rows[0].get('change'), None, 'input is not mutated')

    def test_formatting_and_share(self):
        self.assertEqual(self.ru.fmt_num(1234567), '1,234,567')
        self.assertEqual(self.ru.fmt_num(12.5), '12.5')
        self.assertEqual(self.ru.fmt_num(3.0), '3')
        self.assertEqual(self.ru.fmt_num(None), '')
        self.assertEqual([self.ru.share_of_top(v, 23) for v in (23, 5, 4, 3, 2, 1, 0)], [100, 22, 17, 13, 9, 4, 0])
        self.assertEqual(self.ru.share_of_top(5, 0), 0)
