# -*- coding: utf-8 -*-
"""Pure unit tests (no database): scoring algorithm, bands, edge cases."""
from odoo.tests.common import BaseCase, tagged

from odoo.addons.adoption_intelligence.services import score_calculator as sc
from odoo.addons.adoption_intelligence.services.score_calculator import Totals


def _t(uid, **kw):
    base = dict(active_days=5, records_touched=10, meaningful_edits=10,
                field_edits=20, distinct_fields=20, objects_used=2,
                reports_and_dashboards=3, active_minutes=100, logins=5)
    base.update(kw)
    return Totals(user_id=uid, **base)


@tagged('post_install', '-at_install', 'adoption_pure')
class TestScoring(BaseCase):

    def test_weights_sum_to_100(self):
        self.assertEqual(sum(sc.WEIGHTS.values()), 100)
        self.assertEqual(sc.WEIGHTS, {
            'presence': 15, 'data_activity': 20, 'process_compliance': 25,
            'feature_adoption': 15, 'engagement': 15, 'data_quality': 10})

    def test_percentile_matches_original_lower_nearest_rank(self):
        # floor(0.75 * (n-1)): n=5 -> idx 3, n=4 -> idx 2, n=1 -> idx 0
        self.assertEqual(sc.percentile([1, 2, 3, 4, 5]), 4.0)
        self.assertEqual(sc.percentile([10, 20, 30, 40]), 30.0)
        self.assertEqual(sc.percentile([7]), 7.0)
        self.assertEqual(sc.percentile([]), 0.0)

    def test_everyone_equal_gets_full_score(self):
        users = [_t(i) for i in range(1, 6)]
        bench = sc.compute_benchmarks(users)
        for u in users:
            r = sc.score_user(u, bench)
            self.assertAlmostEqual(r['total_score'], 100.0, places=2)
            self.assertEqual(r['adoption_band'], sc.BAND_POWER_USER)

    def test_component_is_capped_at_one(self):
        users = [_t(i, active_minutes=10) for i in range(1, 5)] + [_t(9, active_minutes=10000)]
        bench = sc.compute_benchmarks(users)
        r = sc.score_user(users[-1], bench)
        self.assertLessEqual(r['engagement_score'], 15.0)
        self.assertLessEqual(r['total_score'], 100.0)

    def test_weighted_contribution(self):
        # Half the benchmark on presence only => 7.5 of 15 points.
        ref = [_t(i, active_days=10) for i in range(1, 6)]
        me = _t(99, active_days=5, records_touched=0, meaningful_edits=0,
                field_edits=0, distinct_fields=0, objects_used=0,
                reports_and_dashboards=0, active_minutes=0)
        bench = sc.compute_benchmarks(ref + [me])
        r = sc.score_user(me, bench)
        self.assertAlmostEqual(r['presence_score'], 7.5, places=2)
        self.assertEqual(r['data_activity_score'], 0.0)

    def test_zero_percentile_never_divides_and_gives_no_free_points(self):
        # Nobody but one user has any engagement => p75 == 0.
        users = [_t(i, active_minutes=0) for i in range(1, 6)] + [_t(6, active_minutes=30)]
        bench = sc.compute_benchmarks(users)
        self.assertEqual(bench['engagement']['method'], 'max_fallback')
        zero_user = sc.score_user(users[0], bench)
        self.assertEqual(zero_user['engagement_score'], 0.0)
        best = sc.score_user(users[-1], bench)
        self.assertEqual(best['engagement_score'], 15.0)
        # original behaviour (bench=1) would have given *any* user with >=1
        # minute the full 15; here a user with 3 of the best 30 gets 1.5.
        mid = _t(7, active_minutes=3)
        bench2 = sc.compute_benchmarks(users + [mid])
        self.assertAlmostEqual(sc.score_user(mid, bench2)['engagement_score'], 1.5, places=2)

    def test_metric_unavailable_for_everyone(self):
        users = [_t(i, active_minutes=0) for i in range(1, 6)]
        bench = sc.compute_benchmarks(users)
        self.assertEqual(bench['engagement']['method'], 'unavailable')
        r = sc.score_user(users[0], bench)
        self.assertEqual(r['engagement_score'], 0.0)
        self.assertIn('engagement', r['notes'])

    def test_no_history_at_all(self):
        bench = sc.compute_benchmarks([])
        r = sc.score_user(Totals(user_id=1), bench)
        self.assertEqual(r['total_score'], 0.0)
        self.assertEqual(r['adoption_band'], sc.BAND_INACTIVE)

    def test_inactive_is_not_the_same_as_low_score(self):
        self.assertEqual(sc.band(0, 0), sc.BAND_INACTIVE)
        self.assertEqual(sc.band(0.5, 1), sc.BAND_AT_RISK)
        self.assertEqual(sc.band(49.99, 3), sc.BAND_AT_RISK)

    def test_band_boundaries(self):
        self.assertEqual(sc.band(90, 1), sc.BAND_POWER_USER)
        self.assertEqual(sc.band(89.99, 1), sc.BAND_HEALTHY)
        self.assertEqual(sc.band(70, 1), sc.BAND_HEALTHY)
        self.assertEqual(sc.band(69.99, 1), sc.BAND_NEEDS_IMPROVEMENT)
        self.assertEqual(sc.band(50, 1), sc.BAND_NEEDS_IMPROVEMENT)

    def test_no_eligible_records_means_zero_quality_not_error(self):
        t = _t(1, records_touched=0, distinct_fields=5)
        self.assertEqual(sc.fields_per_record(t), 0.0)
        bench = sc.compute_benchmarks([_t(2), _t(3), t])
        self.assertEqual(sc.score_user(t, bench)['data_quality_score'], 0.0)

    def test_inactive_users_do_not_shape_the_benchmark(self):
        active = [_t(i) for i in range(1, 6)]
        ghosts = [Totals(user_id=100 + i) for i in range(50)]
        self.assertEqual(sc.compute_benchmarks(active + ghosts)['_population'], 5)

    def test_small_population_is_flagged(self):
        users = [_t(1), _t(2)]
        r = sc.score_user(users[0], sc.compute_benchmarks(users))
        self.assertIn('small reference population', r['notes'])

    def test_total_always_within_0_100(self):
        users = [_t(i, active_days=i, records_touched=i * 3) for i in range(1, 12)]
        bench = sc.compute_benchmarks(users)
        for u in users:
            total = sc.score_user(u, bench)['total_score']
            self.assertTrue(0.0 <= total <= 100.0)
