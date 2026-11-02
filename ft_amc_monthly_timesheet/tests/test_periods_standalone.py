# -*- coding: utf-8 -*-
"""Pure-python tests for models/periods.py.

Runs without Odoo:  python3 tests/test_periods_standalone.py
The module is loaded by file path, so no ``odoo`` import is triggered.
(Not imported from tests/__init__.py on purpose.)
"""
import importlib.util
import os
import unittest
from datetime import date, datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(os.path.dirname(_HERE), 'models', 'periods.py')
_spec = importlib.util.spec_from_file_location('ft_amc_periods', _PATH)
periods = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(periods)


class TestPeriods(unittest.TestCase):

    def test_month_start(self):
        self.assertEqual(periods.month_start(date(2026, 10, 19)), date(2026, 10, 1))
        self.assertEqual(periods.month_start(date(2026, 10, 1)), date(2026, 10, 1))
        self.assertEqual(periods.month_start(date(2026, 12, 31)), date(2026, 12, 1))

    def test_month_end(self):
        self.assertEqual(periods.month_end(date(2026, 10, 5)), date(2026, 10, 31))
        self.assertEqual(periods.month_end(date(2026, 11, 1)), date(2026, 11, 30))
        self.assertEqual(periods.month_end(date(2026, 12, 15)), date(2026, 12, 31))
        self.assertEqual(periods.month_end(date(2026, 2, 1)), date(2026, 2, 28))
        self.assertEqual(periods.month_end(date(2024, 2, 10)), date(2024, 2, 29))

    def test_previous_month(self):
        self.assertEqual(periods.previous_month(date(2026, 11, 5)),
                         (date(2026, 10, 1), date(2026, 10, 31)))
        self.assertEqual(periods.previous_month(date(2026, 11, 30)),
                         (date(2026, 10, 1), date(2026, 10, 31)))
        self.assertEqual(periods.previous_month(date(2026, 11, 1)),
                         (date(2026, 10, 1), date(2026, 10, 31)))

    def test_previous_month_year_rollover(self):
        self.assertEqual(periods.previous_month(date(2027, 1, 5)),
                         (date(2026, 12, 1), date(2026, 12, 31)))

    def test_previous_month_february(self):
        self.assertEqual(periods.previous_month(date(2024, 3, 5)),
                         (date(2024, 2, 1), date(2024, 2, 29)))
        self.assertEqual(periods.previous_month(date(2026, 3, 31)),
                         (date(2026, 2, 1), date(2026, 2, 28)))

    def test_local_bounds_utc_kolkata(self):
        start, end = periods.local_bounds_utc(
            date(2026, 10, 1), date(2026, 10, 31), 'Asia/Kolkata')
        # 1 Oct 00:00 IST (+05:30) -> 30 Sep 18:30 UTC; end exclusive 1 Nov 00:00 IST.
        self.assertEqual(start, datetime(2026, 9, 30, 18, 30))
        self.assertEqual(end, datetime(2026, 10, 31, 18, 30))
        self.assertIsNone(start.tzinfo)
        self.assertIsNone(end.tzinfo)

    def test_local_bounds_utc_utc(self):
        start, end = periods.local_bounds_utc(date(2026, 12, 1), date(2026, 12, 31), 'UTC')
        self.assertEqual(start, datetime(2026, 12, 1))
        self.assertEqual(end, datetime(2027, 1, 1))

    def test_local_bounds_utc_dst(self):
        # Europe/London: October 2026 starts in BST (+1) and ends in GMT (+0)
        # (DST ends 25 Oct 2026).
        start, end = periods.local_bounds_utc(
            date(2026, 10, 1), date(2026, 10, 31), 'Europe/London')
        self.assertEqual(start, datetime(2026, 9, 30, 23, 0))
        self.assertEqual(end, datetime(2026, 11, 1, 0, 0))


if __name__ == '__main__':
    unittest.main(verbosity=2)
