# -*- coding: utf-8 -*-
"""Pure tests of the tracking engine's decision logic, driven by a tiny fake
environment (no database): attribution, points, field eligibility, change rows."""
from odoo.tests.common import BaseCase, tagged

from odoo.addons.adoption_intelligence.services import activity_tracker as t


class FakeCursor:
    class _Pre:
        def __init__(self):
            self.data = {}
    def __init__(self):
        self.precommit = self._Pre()
        self.dbname = 'testdb'


class FakeModel:
    def __init__(self, inherits=None):
        self._inherits = inherits or {}


class FakeEnv:
    def __init__(self, models=None):
        self.cr = FakeCursor()
        self.registry = models or {}
        self.context = {}
        self.uid = 7


class FakeField:
    def __init__(self, ftype, store=True, inherited=False, string='F', selection=None, comodel=None):
        self.type, self.store, self.inherited, self.string = ftype, store, inherited, string
        self._sel, self.comodel_name = selection, comodel

    def _description_selection(self, env):
        return self._sel or []


class FakeRecords:
    def __init__(self, fields):
        self._fields = fields
        self.env = FakeEnv()


RT = {'import_automated': True, 'excluded_field_names': frozenset({'barcode'}),
      'points_create': 3.0, 'points_update': 1.0, 'points_meaningful': 2.0, 'max_value_length': 255}


def cfg(**over):
    base = {'weight': 1.0, 'all_fields': True, 'x2many': False, 'fields': {}, 'label': 'Lead'}
    base.update(over)
    return base


@tagged('post_install', '-at_install', 'adoption_pure')
class TestAttribution(BaseCase):

    def test_first_touch_primary_then_followups_secondary(self):
        env = FakeEnv()
        self.assertEqual(t._classify(env, RT, 'crm.lead', 1, 'web'), ('primary', False))
        self.assertEqual(t._classify(env, RT, 'crm.lead', 1, 'web'), ('secondary', True))
        self.assertEqual(t._classify(env, RT, 'crm.lead', 1, 'web'), ('secondary', True))
        # a different record in the same transaction is the person's own work
        self.assertEqual(t._classify(env, RT, 'crm.lead', 2, 'web'), ('primary', False))

    def test_new_transaction_resets_attribution(self):
        env = FakeEnv()
        t._classify(env, RT, 'crm.lead', 1, 'web')
        env.cr.precommit.data.clear()               # what Odoo does on commit/rollback
        self.assertEqual(t._classify(env, RT, 'crm.lead', 1, 'web'), ('primary', False))

    def test_inherits_delegation_is_secondary(self):
        env = FakeEnv({'res.users': FakeModel({'res.partner': 'partner_id'}), 'res.partner': FakeModel()})
        token = t.enter(env, 'res.users', 'create')
        self.assertEqual(t._classify(env, RT, 'res.partner', 5, 'web'), ('secondary', True))
        t.leave(env, token)
        self.assertEqual(t._classify(env, RT, 'res.partner', 6, 'web'), ('primary', False))

    def test_unrelated_nested_create_stays_primary(self):
        # a sale order creating its lines is the user's own action, not delegation
        env = FakeEnv({'sale.order': FakeModel(), 'sale.order.line': FakeModel()})
        token = t.enter(env, 'sale.order', 'create')
        self.assertEqual(t._classify(env, RT, 'sale.order.line', 9, 'web'), ('primary', False))
        t.leave(env, token)

    def test_source_decides_automation(self):
        for source, expected in (('web', False), ('api', False), ('automation', True), ('other', True), ('import', True)):
            env = FakeEnv()
            self.assertEqual(t._classify(env, RT, 'm.x', 1, source)[1], expected, source)
        env = FakeEnv()
        self.assertFalse(t._classify(env, dict(RT, import_automated=False), 'm.x', 1, 'import')[1])

    def test_stack_enter_leave(self):
        env = FakeEnv()
        a = t.enter(env, 'a.b', 'write')
        b = t.enter(env, 'c.d', 'create')
        t.leave(env, b)
        self.assertEqual(t.txn_state(env)['stack'], [('a.b', 'write')])
        t.leave(env, a)
        self.assertEqual(t.txn_state(env)['stack'], [])

    def test_transaction_id_is_stable_within_a_transaction(self):
        env = FakeEnv()
        self.assertEqual(t._txn_id(env), t._txn_id(env))
        first = t._txn_id(env)
        env.cr.precommit.data.clear()
        self.assertNotEqual(first, t._txn_id(env))

    def test_source_override_and_import_context(self):
        env = FakeEnv()
        env.context = {'adoption_source': 'api'}
        self.assertEqual(t.detect_source(env), 'api')
        env.context = {'import_file': True}
        self.assertEqual(t.detect_source(env), 'import')
        env.context = {}
        self.assertIn(t.detect_source(env), ('automation', 'other'))   # no HTTP request here


@tagged('post_install', '-at_install', 'adoption_pure')
class TestPointsAndEligibility(BaseCase):

    def ch(self, kind='update', meaningful=False, weight=1.0):
        return {'kind': kind, 'meaningful': meaningful, 'weight': weight}

    def test_points_follow_the_original_formula(self):
        self.assertEqual(t._points(RT, cfg(), 'create', []), 3.0)
        self.assertEqual(t._points(RT, cfg(), 'update', []), 1.0)
        # 1 + 2*weight(3) for one meaningful edit
        self.assertEqual(t._points(RT, cfg(), 'update', [self.ch(meaningful=True, weight=3.0)]), 7.0)
        # object weight multiplies everything
        self.assertEqual(t._points(RT, cfg(weight=2.0), 'update', [self.ch(meaningful=True, weight=3.0)]), 14.0)
        self.assertEqual(t._points(RT, cfg(weight=2.0), 'create', []), 6.0)
        self.assertEqual(t._points(RT, cfg(), 'delete', []), 0.0)

    def test_value_at_creation_and_deletion_never_earn_edit_points(self):
        self.assertEqual(t._points(RT, cfg(), 'update', [self.ch(kind='initial', meaningful=True)]), 1.0)
        self.assertEqual(t._points(RT, cfg(), 'update', [self.ch(kind='final', meaningful=True)]), 1.0)

    def test_field_eligibility_rules(self):
        F = FakeField
        c = cfg()
        ok = lambda f, n, conf=c: t._eligible(f, n, conf, RT)  # noqa: E731
        self.assertTrue(ok(F('char'), 'name'))
        self.assertTrue(ok(F('many2one', comodel='res.partner'), 'partner_id'))
        self.assertTrue(ok(F('char', store=False, inherited=True), 'email'))      # _inherits field
        self.assertFalse(ok(F('char', store=False), 'computed_thing'))             # computed / related
        self.assertFalse(ok(F('binary'), 'image_1920'))
        self.assertFalse(ok(F('char'), 'password'))
        self.assertFalse(ok(F('char'), 'oauth_access_token'))
        self.assertFalse(ok(F('datetime'), 'write_date'))
        self.assertFalse(ok(F('one2many'), 'message_ids'))
        self.assertFalse(ok(F('char'), 'barcode'), 'globally excluded name')
        self.assertFalse(ok(F('one2many'), 'order_line'), 'x2many off by default')
        self.assertTrue(ok(F('one2many'), 'order_line', cfg(x2many=True)))

    def test_per_field_policy(self):
        F = FakeField
        excluded = cfg(fields={'city': {'tracked': False}})
        self.assertFalse(t._eligible(F('char'), 'city', excluded, RT))
        only_listed = cfg(all_fields=False, fields={'phone': {'tracked': True}})
        self.assertTrue(t._eligible(F('char'), 'phone', only_listed, RT))
        self.assertFalse(t._eligible(F('char'), 'city', only_listed, RT))

    def test_make_change_old_new_masking_and_relations(self):
        env = FakeEnv()
        recs = FakeRecords({
            'phone': FakeField('char', string='Phone'),
            'stage': FakeField('selection', string='Stage', selection=[('q', 'Qualification'), ('p', 'Proposal')]),
        })
        maps = {}
        c = cfg(fields={'phone': {'meaningful': True, 'weight': 2.0, 'mask': False, 'category': 'Pipeline'}})
        change = t._make_change(env, recs, 'phone', 'update', '111', '222', c, RT, maps)
        self.assertEqual((change['old'], change['new'], change['meaningful'], change['weight']), ('111', '222', True, 2.0))
        sel = t._make_change(env, recs, 'stage', 'update', 'q', 'p', c, RT, maps)
        self.assertEqual((sel['old'], sel['new']), ('Qualification (q)', 'Proposal (p)'))
        masked = cfg(fields={'phone': {'mask': True}})
        m = t._make_change(env, recs, 'phone', 'update', '111', '222', masked, RT, {})
        self.assertEqual((m['old'], m['new'], m['masked']), ('***masked***', '***masked***', True))
        created = t._make_change(env, recs, 'phone', 'initial', None, '555', c, RT, {})
        self.assertEqual((created['old'], created['new']), (None, '555'))
