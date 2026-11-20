# -*- coding: utf-8 -*-
"""Navigation / Activity log / Model analytics / Reports endpoints.
Needs a real Odoo database. NOT run in the authoring sandbox."""
import os
import time

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import tagged

from odoo.addons.adoption_intelligence.services import activity_aggregator as agg

from .common import AdoptionCase


def _key(n):
    return 'nav%021d' % n


@tagged('post_install', '-at_install', 'adoption')
class TestAdoptionScreens(AdoptionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Users = cls.env['res.users']
        gfield = 'group_ids' if 'group_ids' in Users._fields else 'groups_id'
        base = cls.env.ref('base.group_user')
        mgr = cls.env.ref('adoption_intelligence.group_adoption_manager')
        cls.alice = Users.create({'name': 'Alice S', 'login': 'alice_screens', 'email': 'as@x.test', gfield: [(6, 0, [base.id])]})
        cls.bob = Users.create({'name': 'Bob S', 'login': 'bob_screens', 'email': 'bs@x.test', gfield: [(6, 0, [base.id])]})
        cls.boss = Users.create({'name': 'Boss S', 'login': 'boss_screens', 'email': 'cs@x.test', gfield: [(6, 0, [base.id, mgr.id])]})
        cls.D = cls.env['adoption.dashboard']

    def _partner_as(self, user, **vals):
        return self.env['res.partner'].with_user(user).with_context(adoption_source='web').create(dict({'name': 'S-' + user.login}, **vals))

    # ---------------------------------------------------------------- activity log
    def test_activity_log_is_scoped_filtered_and_paginated(self):
        for _i in range(3):
            self._partner_as(self.alice)
        self._partner_as(self.bob)
        own = self.D.with_user(self.alice).get_activity_log(operation='create', limit=2)
        self.assertGreaterEqual(own['total'], 3)
        self.assertEqual(len(own['rows']), 2)
        self.assertTrue(all(r['user'] == 'Alice S' for r in own['rows']))
        page2 = self.D.with_user(self.alice).get_activity_log(operation='create', limit=2, offset=2)
        self.assertFalse({r['id'] for r in own['rows']} & {r['id'] for r in page2['rows']})
        everyone = self.D.with_user(self.boss).get_activity_log(operation='create', limit=200)
        self.assertEqual({'Alice S', 'Bob S'} <= {r['user'] for r in everyone['rows']}, True)

    def test_activity_log_refuses_other_users_to_ordinary_users(self):
        with self.assertRaises(AccessError):
            self.D.with_user(self.alice).get_activity_log(user_id=self.bob.id)

    def test_activity_origin_and_search_filters(self):
        self._partner_as(self.alice, name='Findable Name')
        self.env['res.partner'].create({'name': 'Cron made'})                   # automation
        human = self.D.with_user(self.boss).get_activity_log(origin='human', limit=200)
        self.assertTrue(all(not r['automated'] for r in human['rows']))
        found = self.D.with_user(self.boss).get_activity_log(search='Findable', limit=50)
        self.assertTrue(found['rows'] and all('Findable' in r['record'] for r in found['rows']))

    def test_old_new_values_hidden_from_other_ordinary_users(self):
        p = self._partner_as(self.alice, phone='1')
        self.new_request()
        p.with_user(self.alice).with_context(adoption_source='web').write({'phone': '2'})
        upd = self.Log.search([('record_id', '=', p.id), ('operation', '=', 'update')])
        self.assertEqual([c['new'] for c in self.D.with_user(self.alice).get_activity_changes(activity_id=upd.id)], ['2'])
        self.assertEqual(self.D.with_user(self.bob).get_activity_changes(activity_id=upd.id), [])
        self.assertEqual([c['new'] for c in self.D.with_user(self.boss).get_activity_changes(activity_id=upd.id)], ['2'])

    def test_export_row_cap(self):
        data = self.D.with_user(self.boss).get_activity_log(limit=10 ** 6, export=True)
        self.assertLessEqual(data['limit'], 5000)
        self.assertLessEqual(self.D.with_user(self.boss).get_activity_log(limit=10 ** 6)['limit'], 200)

    # ---------------------------------------------------------------- navigation
    def _visit(self, n, rid, user):
        ev = {'t': 'visit', 'key': _key(n), 'bs': _key(900 + n), 'ev': 'record_view', 'kind': 'record',
              'model': 'res.partner', 'rid': rid, 'ts': int(time.time() * 1000)}
        self.env['adoption.tracker'].with_user(user).track({'events': [ev]})

    def test_navigation_scope_and_counts(self):
        pa, pb = self._partner_as(self.alice), self._partner_as(self.bob)
        self._visit(1, pa.id, self.alice)
        self._visit(2, pb.id, self.bob)
        mine = self.D.with_user(self.alice).get_navigation()
        self.assertEqual({e['user'] for e in mine['events']}, {'Alice S'})
        self.assertGreaterEqual(mine['kpis']['records'], 1)
        allv = self.D.with_user(self.boss).get_navigation()
        self.assertEqual({'Alice S', 'Bob S'} <= {e['user'] for e in allv['events']}, True)
        with self.assertRaises(AccessError):
            self.D.with_user(self.alice).get_navigation(user_id=self.bob.id)

    def test_navigation_event_type_filter_and_trend_length(self):
        p = self._partner_as(self.alice)
        self._visit(3, p.id, self.alice)
        only = self.D.with_user(self.alice).get_navigation(event_type='record_view')
        self.assertTrue(only['events'] and all(e['type'] == 'record_view' for e in only['events']))
        start = fields.Date.subtract(fields.Date.context_today(self.env.user), days=6)
        data = self.D.with_user(self.alice).get_navigation(date_from=start, date_to=fields.Date.context_today(self.env.user))
        self.assertEqual(len(data['trend']), 7, 'one point per day, zero-filled')

    # ---------------------------------------------------------------- model analytics
    def test_model_analytics_manager_only_and_real_data(self):
        self._partner_as(self.alice, phone='1')
        with self.assertRaises(AccessError):
            self.D.with_user(self.alice).get_model_analytics()
        data = self.D.with_user(self.boss).get_model_analytics()
        row = next(r for r in data['rows'] if r['model'] == 'res.partner')
        self.assertGreaterEqual(row['created'], 1)
        detail = self.D.with_user(self.boss).get_model_analytics(model_name='res.partner')['detail']
        self.assertEqual(detail['model'], 'res.partner')
        self.assertTrue(detail['config']['create'])
        self.assertTrue(any(u['name'] == 'Alice S' for u in detail['top_users']))

    # ---------------------------------------------------------------- reports
    def test_summary_report_buckets_and_totals(self):
        self._partner_as(self.alice, phone='1')
        today = fields.Date.context_today(self.env.user)
        agg.rollup_day(self.env, today)
        for gran in ('day', 'week', 'month'):
            rep = self.D.with_user(self.boss).get_summary_report(
                date_from=fields.Date.subtract(today, days=40), date_to=today, granularity=gran)
            self.assertEqual(rep['granularity'], gran)
            self.assertGreaterEqual(rep['totals']['created'], 1)
            self.assertEqual(sum(r['created'] for r in rep['rows']), rep['totals']['created'], gran)
        self.assertEqual(self.D.with_user(self.boss).get_summary_report(granularity='bogus')['granularity'], 'day')

    def test_summary_report_ordinary_user_sees_only_self(self):
        self._partner_as(self.alice)
        self._partner_as(self.bob)
        today = fields.Date.context_today(self.env.user)
        mine = self.D.with_user(self.alice).get_summary_report(date_from=today, date_to=today)
        everyone = self.D.with_user(self.boss).get_summary_report(date_from=today, date_to=today)
        self.assertLess(mine['totals']['created'], everyone['totals']['created'])
        with self.assertRaises(AccessError):
            self.D.with_user(self.alice).get_summary_report(user_id=self.bob.id)

    def test_field_change_report(self):
        p = self._partner_as(self.alice, phone='1')
        self.new_request()
        p.with_user(self.alice).with_context(adoption_source='web').write({'phone': '2'})
        rep = self.D.with_user(self.boss).get_field_change_report(model_name='res.partner', kind='update')
        self.assertTrue(any(r['name'] == 'phone' for r in rep['summary']))
        row = next(r for r in rep['rows'] if r['field'] and r['new'] == '2')
        self.assertEqual((row['old'], row['new'], row['user']), ('1', '2', 'Alice S'))
        meaningful = self.D.with_user(self.boss).get_field_change_report(model_name='res.partner', meaningful_only=True)
        self.assertTrue(all(r['meaningful'] for r in meaningful['rows']))

    # ---------------------------------------------------------------- shell
    def test_sidebar_no_longer_offers_detail_lists(self):
        path = os.path.join(os.path.dirname(__file__), '..', 'static', 'src', 'xml', 'adoption_dashboard.xml')
        with open(path) as handle:
            source = handle.read()
        self.assertNotIn('Detail lists', source)
        self.assertIn('analyticsTabs', source)


@tagged('post_install', '-at_install', 'adoption')
class TestAdoptionScreenPdf(AdoptionCase):
    """Server-side "Download PDF". Needs a real Odoo database. NOT run in the authoring sandbox."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Users = cls.env['res.users']
        gfield = 'group_ids' if 'group_ids' in Users._fields else 'groups_id'
        base = cls.env.ref('base.group_user')
        mgr = cls.env.ref('adoption_intelligence.group_adoption_manager')
        cls.alice = Users.create({'name': 'Alice P', 'login': 'alice_pdf', 'email': 'ap@x.test', gfield: [(6, 0, [base.id])]})
        cls.bob = Users.create({'name': 'Bob P', 'login': 'bob_pdf', 'email': 'bp@x.test', gfield: [(6, 0, [base.id])]})
        cls.boss = Users.create({'name': 'Boss P', 'login': 'boss_pdf', 'email': 'cp@x.test', gfield: [(6, 0, [base.id, mgr.id])]})
        cls.Report = 'report.adoption_intelligence.report_screen'

    def _values(self, user, **data):
        return self.env[self.Report].with_user(user)._get_report_values([], data)

    def test_every_screen_builds_for_a_manager(self):
        self.env['res.partner'].with_user(self.alice).with_context(adoption_source='web').create({'name': 'PDF probe', 'phone': '1'})
        for screen in ('overview', 'leaderboard', 'user', 'navigation', 'activity', 'models', 'reports'):
            doc = self._values(self.boss, screen=screen)['doc']
            self.assertTrue(doc['title'] and doc['sections'], screen)
            for sec in doc['sections']:
                self.assertIn(sec['kind'], ('table', 'bars'))
        fields_doc = self._values(self.boss, screen='fields', model_name='res.partner')['doc']
        self.assertEqual(fields_doc['title'], 'Field adoption')

    def test_unknown_screen_and_bad_options_are_rejected_or_ignored(self):
        with self.assertRaises(UserError):
            self._values(self.boss, screen='../../etc/passwd')
        doc = self._values(self.boss, screen='activity', model_name='x; drop table y', user_id='abc', date_from='garbage')['doc']
        self.assertIn('sections', doc, 'bad options fall back to defaults instead of failing or being trusted')

    def test_pdf_never_exceeds_what_the_screen_allows(self):
        with self.assertRaises(AccessError):
            self._values(self.alice, screen='models')                          # manager-only screen
        with self.assertRaises(AccessError):
            self._values(self.alice, screen='user', user_id=self.bob.id)       # someone else's data
        self.assertEqual(self._values(self.alice, screen='user')['doc']['scope'], 'My activity')

    def test_reports_comparison_table_has_change_column(self):
        self.env['res.partner'].with_user(self.alice).with_context(adoption_source='web').create({'name': 'PDF cmp', 'phone': '1'})
        doc = self._values(self.boss, screen='reports', granularity='month')['doc']
        table = next(s for s in doc['sections'] if s['title'] == 'Comparison table')
        self.assertEqual(table['columns'][-1], 'Change vs previous')
        self.assertTrue(table['rows'])
        self.assertEqual(table['rows'][-1][-1], '\u2014', 'the oldest period has no previous period')

    def test_pdf_html_renders(self):
        html = self.env['ir.actions.report'].with_user(self.boss)._render_qweb_html(
            'adoption_intelligence.report_screen', [], data={'screen': 'reports', 'granularity': 'month'})[0]
        self.assertIn(b'Comparison table', html)

    def test_new_header_and_filters_exist_in_the_shell_template(self):
        path = os.path.join(os.path.dirname(__file__), '..', 'static', 'src', 'xml', 'adoption_dashboard.xml')
        with open(path) as handle:
            source = handle.read()
        for needle in ('Download PDF', 'Group by Month', 'ad-topbar', 'ad-pagehead', 'Filter</label>', 'All users (org)'):
            self.assertIn(needle, source)


@tagged('post_install', '-at_install', 'adoption')
class TestAdoptionFieldAdoptionAllModels(AdoptionCase):
    """Field adoption with no model chosen = every tracked model. Needs a real database; NOT run here."""

    def test_all_models_is_the_default_and_rows_carry_their_model(self):
        p = self.partner(phone='1')
        self.new_request()
        p.with_context(adoption_source='web').write({'phone': '2'})
        D = self.env['adoption.dashboard']
        everything = D.get_field_adoption()
        self.assertTrue(everything['all_models'])
        self.assertEqual(everything['label'], 'All models')
        row = next(r for r in everything['rows'] if r['model'] == 'res.partner' and r['field'] == 'phone')
        self.assertEqual(row['model_label'], self.cfg.model_label)
        self.assertGreaterEqual(row['edits'], 1)
        single = D.get_field_adoption('res.partner')
        self.assertFalse(single['all_models'])
        self.assertTrue(all(r['model'] == 'res.partner' for r in single['rows']))
        self.assertLessEqual(len(single['rows']), len(everything['rows']))

    def test_not_enough_history_is_unknown_not_unused(self):
        self.cfg.sudo().write({'observed_since': fields.Datetime.now()})          # tracking "started today"
        from datetime import timedelta
        start = fields.Date.context_today(self.env.user) - timedelta(days=30)
        data = self.env['adoption.dashboard'].get_field_adoption(date_from=start)
        self.assertFalse([u for u in data['unused'] if u['model'] == 'res.partner'])
        self.assertTrue(data['warnings'])

