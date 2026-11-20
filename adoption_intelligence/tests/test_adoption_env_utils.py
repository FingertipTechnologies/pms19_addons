# -*- coding: utf-8 -*-
"""Pure tests: the test-mode probe must work on Odoo 17/18 AND 19 (no database)."""
from odoo.tests.common import BaseCase, tagged

from odoo.addons.adoption_intelligence.services.env_utils import in_test_mode


class _Env:
    def __init__(self, registry):
        self.registry = registry


@tagged('post_install', '-at_install', 'adoption_pure')
class TestInTestMode(BaseCase):

    def test_odoo_17_18_method(self):
        class Registry:
            def in_test_mode(self):
                return True
        self.assertTrue(in_test_mode(_Env(Registry())))

        class Normal:
            def in_test_mode(self):
                return False
        self.assertFalse(in_test_mode(_Env(Normal())))

    def test_odoo_19_has_no_method_only_a_flag(self):
        class Registry:                      # accessing .in_test_mode raises AttributeError, as in 19
            test_mode = True
        self.assertTrue(in_test_mode(_Env(Registry())))

        class Production:
            test_mode = False
        self.assertFalse(in_test_mode(_Env(Production())))

    def test_test_cursor_counts_as_test_mode(self):
        class Registry:
            test_cr = object()
        self.assertTrue(in_test_mode(_Env(Registry())))

        class NoCursor:
            test_cr = None
        self.assertFalse(in_test_mode(_Env(NoCursor())))

    def test_never_raises_and_defaults_to_production(self):
        class Broken:
            def in_test_mode(self):
                raise RuntimeError('boom')
        self.assertFalse(in_test_mode(_Env(Broken())))
        self.assertFalse(in_test_mode(_Env(object())))
