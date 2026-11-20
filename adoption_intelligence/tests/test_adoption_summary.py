# -*- coding: utf-8 -*-
"""Needs a real Odoo database. NOT run in the authoring sandbox."""
from odoo import fields
from odoo.tests.common import tagged

from odoo.addons.adoption_intelligence.services import activity_aggregator as agg

from .common import AdoptionCase


@tagged('post_install', '-at_install', 'adoption')
class TestAdoptionSummary(AdoptionCase):

    def _generate(self):
        p = self.partner(phone='1')
        self.new_request()
        p.with_context(adoption_source='web').write({'phone': '2'})
        return p

    def test_rollup_values_and_idempotency(self):
        self._generate()
        day = fields.Date.context_today(self.env.user)
        agg.rollup_day(self.env, day)
        Summary = self.env['adoption.daily.summary'].sudo()
        row = Summary.search([('user_id', '=', self.env.uid), ('summary_date', '=', day), ('model_name', '=', 'res.partner')])
        self.assertEqual(len(row), 1)
        self.assertGreaterEqual(row.records_created, 1)
        self.assertGreaterEqual(row.records_updated, 1)
        self.assertGreaterEqual(row.meaningful_field_edits, 1)
        before = Summary.search_count([('summary_date', '=', day)])
        agg.rollup_day(self.env, day)
        agg.rollup_day(self.env, day)
        self.assertEqual(Summary.search_count([('summary_date', '=', day)]), before, 'no duplicates on re-run')

    def test_automated_activity_is_counted_but_not_credited(self):
        self.env['res.partner'].create({'name': 'Automated'})
        day = fields.Date.context_today(self.env.user)
        rows = agg.compute_day(self.env, day, [self.env.uid])
        self.assertGreaterEqual(rows[(self.env.uid, 'res.partner')]['automated_changes'], 1)

    def test_expired_detail_is_not_recomputed_over_summary(self):
        old = fields.Date.subtract(fields.Date.context_today(self.env.user), days=500)
        self.assertIsNone(agg.rollup_day(self.env, old, force=True))

    def test_unique_constraint_on_summary(self):
        day = fields.Date.context_today(self.env.user)
        S = self.env['adoption.daily.summary'].sudo().with_context(adoption_internal=True)
        S.create({'user_id': self.env.uid, 'summary_date': day, 'model_name': 'x.y'})
        with self.assertRaises(Exception), self.env.cr.savepoint():
            S.create({'user_id': self.env.uid, 'summary_date': day, 'model_name': 'x.y'})

    def test_scores_are_repeatable_and_bounded(self):
        self._generate()
        Score = self.env['adoption.user.score']
        start, end = Score._period_bounds('month', fields.Date.context_today(self.env.user))
        Score.calculate_period(start, end, 'month')
        n = Score.sudo().search_count([('period_start', '=', start)])
        Score.calculate_period(start, end, 'month')
        self.assertEqual(Score.sudo().search_count([('period_start', '=', start)]), n, 'no duplicate score rows')
        for s in Score.sudo().search([('period_start', '=', start)]):
            self.assertTrue(0 <= s.total_score <= 100)
            self.assertAlmostEqual(s.total_score, s.presence_score + s.data_activity_score + s.process_compliance_score
                                   + s.feature_adoption_score + s.engagement_score + s.data_quality_score, delta=0.06)

    def test_retention_purges_detail_but_keeps_summaries(self):
        p = self.partner()
        old = fields.Date.subtract(fields.Date.context_today(self.env.user), days=200)
        log = self.logs(p, 'create')
        log.with_context(adoption_internal=True).write({'activity_date': old})
        S = self.env['adoption.settings']._get()
        S.last_rollup_date = fields.Date.subtract(fields.Date.context_today(self.env.user), days=1)
        self.env['adoption.activity.log']._cron_purge_expired()
        self.assertFalse(self.Log.search([('id', '=', log.id)]))
