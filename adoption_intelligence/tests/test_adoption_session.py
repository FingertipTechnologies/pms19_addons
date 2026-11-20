# -*- coding: utf-8 -*-
"""Needs a real Odoo database. NOT run in the authoring sandbox."""
import time

from odoo.tests.common import tagged

from .common import AdoptionCase


def _key(n):
    return ('k%023d' % n)


@tagged('post_install', '-at_install', 'adoption')
class TestAdoptionSession(AdoptionCase):

    def setUp(self):
        super().setUp()
        self.api = self.env['adoption.tracker']
        self.Session = self.env['adoption.active.session'].sudo()
        self.Nav = self.env['adoption.navigation.log'].sudo()

    def _visit(self, key, rid, **kw):
        ev = {'t': 'visit', 'key': key, 'bs': _key(900), 'ev': 'record_view', 'kind': 'record',
              'model': 'res.partner', 'rid': rid, 'ts': int(time.time() * 1000)}
        ev.update(kw)
        return ev

    def test_record_view_creates_nav_and_session(self):
        p = self.partner()
        res = self.api.track({'events': [self._visit(_key(1), p.id)]})
        self.assertEqual(res['accepted'], 1)
        self.assertEqual(self.Nav.search_count([('event_key', '=', _key(1)), ('event_type', '=', 'record_view')]), 1)
        s = self.Session.search([('session_key', '=', _key(1))])
        self.assertEqual((s.record_id, s.model_name, s.user_id), (p.id, 'res.partner', self.env.user))

    def test_user_id_in_payload_is_ignored(self):
        p = self.partner()
        other = self.env.ref('base.public_user')
        self.api.track({'events': [dict(self._visit(_key(2), p.id), user_id=other.id, uid=other.id)]})
        self.assertEqual(self.Nav.search([('event_key', '=', _key(2))]).user_id, self.env.user)

    def test_heartbeat_is_idempotent_and_monotonic(self):
        p = self.partner()
        self.api.track({'events': [self._visit(_key(3), p.id)]})
        beat = {'t': 'beat', 'key': _key(3), 'seq': 1, 'act': 20, 'ela': 25}
        self.api.track({'events': [beat]})
        self.api.track({'events': [beat]})                                    # duplicate
        self.api.track({'events': [dict(beat, seq=0, act=5, ela=6)]})         # stale / reordered
        s = self.Session.search([('session_key', '=', _key(3))])
        self.assertEqual((s.active_seconds, s.heartbeat_count), (20, 1))
        self.assertEqual(s.idle_seconds, s.elapsed_seconds - s.active_seconds)

    def test_idle_time_is_not_credited(self):
        p = self.partner()
        self.api.track({'events': [self._visit(_key(4), p.id)]})
        self.api.track({'events': [{'t': 'beat', 'key': _key(4), 'seq': 1, 'act': 10, 'ela': 600}]})
        s = self.Session.search([('session_key', '=', _key(4))])
        self.assertLessEqual(s.active_seconds, 10)
        self.assertLessEqual(s.elapsed_seconds, 70, 'server clock caps what the client may claim')

    def test_duplicate_visit_is_not_duplicated(self):
        p = self.partner()
        for _i in range(3):
            self.api.track({'events': [self._visit(_key(5), p.id)]})
        self.assertEqual(self.Nav.search_count([('event_key', '=', _key(5))]), 1)
        self.assertEqual(self.Session.search_count([('session_key', '=', _key(5))]), 1)

    def test_invalid_payloads_are_rejected(self):
        self.assertEqual(self.api.track('nope').get('error'), 'bad_payload')
        res = self.api.track({'events': [{'t': 'visit', 'key': 'x', 'ev': 'record_view'},
                                         self._visit(_key(6), 1, model='x; drop table y')]})
        self.assertEqual(res['accepted'], 0)
        self.assertEqual(self.api.track({'events': [self._visit(_key(i), 1) for i in range(100, 160)]}).get('error'), 'too_many_events')

    def test_cannot_record_view_of_unreadable_or_missing_record(self):
        res = self.api.track({'events': [self._visit(_key(7), 99999999)]})
        nav = self.Nav.search([('event_key', '=', _key(7))])
        self.assertEqual(nav.event_type, 'page_view', 'missing record is downgraded, never stored as a record view')
        self.assertFalse(nav.record_id)

    def test_unconfigured_model_record_is_not_stored(self):
        self.cfg.track_read = False
        p = self.partner()
        self.api.track({'events': [self._visit(_key(8), p.id)]})
        self.assertFalse(self.Nav.search([('event_key', '=', _key(8))]).record_id)
        self.cfg.track_read = True

    def test_own_models_are_never_tracked(self):
        self.api.track({'events': [self._visit(_key(9), 1, model='adoption.activity.log')]})
        self.assertFalse(self.Nav.search([('event_key', '=', _key(9))]))

    def test_stale_sessions_are_closed_at_last_heartbeat(self):
        p = self.partner()
        self.api.track({'events': [self._visit(_key(10), p.id)]})
        s = self.Session.search([('session_key', '=', _key(10))])
        s.with_context(adoption_internal=True).write({'last_beat_at': '2000-01-01 00:00:00'})
        self.env['adoption.active.session']._cron_close_stale()
        self.assertEqual((s.state, str(s.ended_at)), ('stale', '2000-01-01 00:00:00'))

    def test_login_is_not_duplicated_by_navigation(self):
        L = self.env['adoption.login.summary']
        L._register_login(self.env.user)
        n = self.env['adoption.login.summary'].sudo().search([('user_id', '=', self.env.user.id)]).login_count
        self.api.track({'events': [self._visit(_key(11), 1)]})
        self.assertEqual(self.env['adoption.login.summary'].sudo().search([('user_id', '=', self.env.user.id)]).login_count, n)

    def test_client_config_names_the_user_for_local_storage_only(self):
        self.assertEqual(self.env['adoption.tracker'].get_client_config()['uid'], self.env.uid)
        # ...and identity is still taken from the session, never from the payload (see test_user_id_in_payload_is_ignored)

