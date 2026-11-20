# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

from . import _compat

_logger = logging.getLogger(__name__)
MOBILE_HINTS = ('android', 'iphone', 'ipad', 'mobile')


class AdoptionLoginSummary(models.Model):
    """Logins per user per day.

    Terms used throughout the module
    --------------------------------
    logged in            an authentication happened (this model)
    active browser session  the web client reported at least one visit
                          (``session_count``; adoption.navigation.log)
    actively interacting  visible + focused + recent input
                          (adoption.active.session.active_seconds)
    """
    _name = 'adoption.login.summary'
    _inherit = ['adoption.immutable.mixin']
    _description = 'Adoption Login Summary'
    _order = 'login_date desc, user_id'

    user_id = fields.Many2one('res.users', required=True, index=True, ondelete='cascade')
    login_date = fields.Date(required=True, index=True)
    login_count = fields.Integer()
    first_login = fields.Datetime()
    last_login = fields.Datetime()
    browser_logins = fields.Integer(string='Browser')
    mobile_logins = fields.Integer(string='Mobile')
    api_logins = fields.Integer(string='API')
    session_count = fields.Integer(string='Active browser sessions')
    first_activity = fields.Datetime()
    last_activity = fields.Datetime()

    if _compat.HAS_CONSTRAINT:
        _user_day_uniq = models.Constraint('UNIQUE(user_id, login_date)', 'One login summary per user per day.')
    else:
        _sql_constraints = [('user_day_uniq', 'unique(user_id, login_date)', 'One login summary per user per day.')]

    @api.model
    def _login_channel(self):
        """browser / mobile / api, from the HTTP request that authenticated."""
        try:
            from odoo.http import request
            if not request or request.httprequest is None:
                return 'api'
            path = request.httprequest.path or ''
            if path.startswith(('/xmlrpc', '/jsonrpc', '/json/')):
                return 'api'
            agent = (request.httprequest.headers.get('User-Agent') or '').lower()
            return 'mobile' if any(h in agent for h in MOBILE_HINTS) else 'browser'
        except Exception:  # noqa: BLE001
            return 'browser'

    @api.model
    def _register_login(self, users):
        """Idempotent upsert; safe under concurrent logins (unique constraint +
        retry).  Excluded users and, by default, portal users are not recorded."""
        runtime = self.env['adoption.settings']._runtime()
        if not runtime['tracking_enabled']:
            return
        channel = self._login_channel()
        now = fields.Datetime.now()
        Summary = self.sudo().with_context(adoption_internal=True)
        for user in users.sudo():
            if user.id in runtime['excluded_user_ids'] or (runtime['internal_only'] and user.share):
                continue
            day = fields.Datetime.context_timestamp(user, now).date()
            row = Summary.search([('user_id', '=', user.id), ('login_date', '=', day)], limit=1)
            if not row:
                try:
                    with self.env.cr.savepoint(flush=False):
                        row = Summary.create({
                            'user_id': user.id, 'login_date': day, 'first_login': now})
                except Exception:  # lost the race: someone else created it
                    row = Summary.search([('user_id', '=', user.id), ('login_date', '=', day)], limit=1)
            if row:
                row.write({
                    'login_count': row.login_count + 1,
                    'last_login': now,
                    'first_login': row.first_login or now,
                    '%s_logins' % channel: row['%s_logins' % channel] + 1,
                })

    @api.model
    def _cron_sync_logins(self):
        """Job 1: reconcile login summaries with what the web client reported.

        Login rows are written live by the authentication hook; this job adds
        the *engagement* side (active browser sessions, first/last activity)
        and closes sessions whose tab disappeared.  Idempotent.
        """
        closed = self.env['adoption.active.session']._cron_close_stale()
        settings = self.env['adoption.settings']._get()
        last = settings.last_rollup_date or fields.Date.today()
        start = fields.Date.subtract(last, days=2)
        NavRead = self.env['adoption.navigation.log'].sudo()
        rows = NavRead._read_group(
            [('activity_date', '>=', start), ('user_id', '!=', False)],
            ['user_id', 'activity_date'],
            ['browser_session:count_distinct', 'navigation_datetime:min', 'navigation_datetime:max'])
        Summary = self.sudo().with_context(adoption_internal=True)
        touched = 0
        for user, day, sessions, first, last_seen in rows:
            row = Summary.search([('user_id', '=', user.id), ('login_date', '=', day)], limit=1)
            vals = {'session_count': sessions, 'first_activity': first, 'last_activity': last_seen}
            if row:
                if any(row[k] != v for k, v in vals.items()):
                    row.write(vals)
            else:
                # Active in the browser without a recorded login that day
                # (session cookie survived overnight): record presence, not a login.
                Summary.create(dict(vals, user_id=user.id, login_date=day, login_count=0))
            touched += 1
        _logger.info('Adoption login sync: %s user-days reconciled, %s stale sessions closed.', touched, closed)
        return touched
