# -*- coding: utf-8 -*-
"""Needs a real Odoo database. NOT run in the authoring sandbox."""
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import tagged

from .common import AdoptionCase


@tagged('post_install', '-at_install', 'adoption')
class TestAdoptionSecurity(AdoptionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Users = cls.env['res.users']
        gfield = 'group_ids' if 'group_ids' in Users._fields else 'groups_id'   # renamed in newer Odoo
        base = cls.env.ref('base.group_user')
        mgr = cls.env.ref('adoption_intelligence.group_adoption_manager')
        cls.alice = Users.create({'name': 'Alice A', 'login': 'alice_adopt', 'email': 'a@x.test', gfield: [(6, 0, [base.id])]})
        cls.bob = Users.create({'name': 'Bob B', 'login': 'bob_adopt', 'email': 'b@x.test', gfield: [(6, 0, [base.id])]})
        cls.boss = Users.create({'name': 'Boss', 'login': 'boss_adopt', 'email': 'c@x.test', gfield: [(6, 0, [base.id, mgr.id])]})

    def _as(self, user):
        return self.env['adoption.activity.log'].with_user(user)

    def test_user_sees_only_own_activity(self):
        self.env['res.partner'].with_user(self.alice).with_context(adoption_source='web').create({'name': 'A-made'})
        self.env['res.partner'].with_user(self.bob).with_context(adoption_source='web').create({'name': 'B-made'})
        seen = self._as(self.alice).search([])
        self.assertTrue(seen)
        self.assertEqual(set(seen.mapped('user_id').ids), {self.alice.id})

    def test_manager_sees_everyone(self):
        self.env['res.partner'].with_user(self.alice).with_context(adoption_source='web').create({'name': 'A-made 2'})
        self.assertIn(self.alice, self._as(self.boss).search([]).mapped('user_id'))

    def test_nobody_can_write_or_create_audit_rows(self):
        log = self.Log.search([], limit=1) or self.logs(self.partner(), 'create')
        for user in (self.alice, self.boss):
            with self.assertRaises((AccessError, UserError)):
                self._as(user).browse(log.id).write({'operation': 'delete'})
            with self.assertRaises(AccessError):
                self._as(user).create({'model_name': 'x.y', 'operation': 'create', 'source': 'web',
                                       'activity_datetime': '2026-01-01 00:00:00', 'activity_date': '2026-01-01'})

    def test_only_admin_can_change_configuration(self):
        for user in (self.alice, self.boss):
            with self.assertRaises(AccessError):
                self.env['adoption.tracking.config'].with_user(user).create({'model_id': self.env['ir.model']._get('res.country').id})

    def test_dashboard_refuses_other_users_data_to_ordinary_users(self):
        D = self.env['adoption.dashboard']
        with self.assertRaises(AccessError):
            D.with_user(self.alice).get_user_explorer(self.bob.id)
        with self.assertRaises(AccessError):
            D.with_user(self.alice).get_health()
        self.assertEqual(D.with_user(self.alice).get_user_explorer()['user']['id'], self.alice.id)
        self.assertEqual(D.with_user(self.boss).get_user_explorer(self.alice.id)['user']['id'], self.alice.id)

    def test_dashboard_uses_real_data(self):
        p = self.env['res.partner'].with_user(self.alice).with_context(adoption_source='web').create({'name': 'Real', 'phone': '1'})
        data = self.env['adoption.dashboard'].with_user(self.boss).get_user_explorer(self.alice.id)
        self.assertTrue(any(a['record_id'] == p.id for a in data['activity']))
        self.assertGreaterEqual(data['kpis']['created'], 1)

    def test_only_admin_can_recalculate_or_self_test(self):
        with self.assertRaises(AccessError):
            self.env['adoption.user.score'].with_user(self.boss).recalculate('2026-01-01')
        with self.assertRaises(AccessError):
            self.env['adoption.dashboard'].with_user(self.boss).run_self_test()

    def test_excluded_user_is_not_tracked(self):
        self.alice.sudo().adoption_excluded = True
        p = self.env['res.partner'].with_user(self.alice).with_context(adoption_source='web').create({'name': 'Ghost'})
        self.assertFalse(self.logs(p))
        self.alice.sudo().adoption_excluded = False

    def test_module_needs_no_chrome_extension(self):
        # The whole pipeline is server + web client: nothing references an extension.
        self.assertIn('adoption.tracker', self.env)
        self.assertTrue(self.env['adoption.tracker'].get_client_config()['enabled'])
