# -*- coding: utf-8 -*-
"""Pure unit tests (no database): value normalisation and field-change logic."""
from datetime import date, datetime

from odoo.tests.common import BaseCase, tagged

from odoo.addons.adoption_intelligence.services import value_utils as vu


@tagged('post_install', '-at_install', 'adoption_pure')
class TestValueUtils(BaseCase):

    def test_unchanged_values_are_not_changes(self):
        cases = [
            ('char', 'a', 'a'), ('char', False, ''), ('text', None, False),
            ('integer', 3, 3), ('float', 1.0, 1.0000000001),
            ('monetary', 10.5, 10.5), ('boolean', True, True),
            ('date', date(2026, 1, 1), date(2026, 1, 1)),
            ('datetime', datetime(2026, 1, 1, 8, 0), datetime(2026, 1, 1, 8, 0)),
            ('selection', 'draft', 'draft'), ('many2one', 5, 5),
            ('many2many', [3, 1, 2], [1, 2, 3]), ('one2many', [], []),
        ]
        for ftype, old, new in cases:
            self.assertFalse(vu.changed(ftype, old, new), (ftype, old, new))

    def test_real_changes_are_detected(self):
        cases = [
            ('char', 'a', 'b'), ('char', False, 'x'), ('integer', 1, 2),
            ('float', 1.0, 1.5), ('boolean', True, False),
            ('date', date(2026, 1, 1), date(2026, 1, 2)),
            ('selection', 'draft', 'sale'), ('many2one', 5, False),
            ('many2one', False, 7), ('many2many', [1], [1, 2]),
        ]
        for ftype, old, new in cases:
            self.assertTrue(vu.changed(ftype, old, new), (ftype, old, new))

    def test_boolean_false_is_a_real_value(self):
        self.assertTrue(vu.changed('boolean', True, False))
        self.assertFalse(vu.changed('boolean', False, False))

    def test_truncation_cannot_hide_a_change(self):
        a = 'x' * 300 + 'A'
        b = 'x' * 300 + 'B'
        self.assertTrue(vu.changed('text', a, b))
        self.assertEqual(len(vu.format_value('text', a, max_len=255)), 255)

    def test_sensitive_names(self):
        for name in ('password', 'password_crypt', 'oauth_access_token', 'api_key',
                     'totp_secret', 'private_key', 'pin', 'client_secret'):
            self.assertTrue(vu.is_sensitive_name(name), name)
        for name in ('footprint', 'stage_id', 'phone', 'expected_revenue',
                     'tokenless', 'opinion', 'spinner'):
            self.assertFalse(vu.is_sensitive_name(name), name)

    def test_system_fields_are_excluded(self):
        for name in ('write_date', 'create_uid', 'message_ids', 'activity_state',
                     'message_main_attachment_id', 'display_name'):
            self.assertTrue(vu.is_system_field(name), name)
        self.assertFalse(vu.is_system_field('stage_id'))

    def test_format_many2one_selection_and_masking(self):
        self.assertEqual(vu.format_value('many2one', 5, display={5: 'Proposal'}), 'Proposal [#5]')
        self.assertEqual(vu.format_value('many2one', 5), '[#5]')
        self.assertEqual(vu.format_value('selection', 'sale', selection={'sale': 'Sales Order'}),
                         'Sales Order (sale)')
        self.assertEqual(vu.format_value('char', 'secret!', masked=True), vu.MASKED_VALUE)
        self.assertIsNone(vu.format_value('char', None, masked=True))
        self.assertIsNone(vu.format_value('char', None))

    def test_format_numbers_and_booleans(self):
        self.assertEqual(vu.format_value('float', 1000.0), '1000')
        self.assertEqual(vu.format_value('monetary', 12.5), '12.5')
        self.assertEqual(vu.format_value('float', 0.0), '0')
        self.assertEqual(vu.format_value('boolean', False), 'False')

    def test_x2many_delta(self):
        old, new = vu.comparable('one2many', [1, 2]), vu.comparable('one2many', [2, 3, 4])
        self.assertEqual(vu.x2many_delta(old, new), ([3, 4], [1]))
        self.assertEqual(vu.format_value('one2many', new, delta=([3, 4], [1])), '+#3, #4 -#1')
