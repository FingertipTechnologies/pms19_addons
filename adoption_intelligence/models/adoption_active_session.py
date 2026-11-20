# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models

from ..services import session_math
from . import _compat


class AdoptionActiveSession(models.Model):
    """One timed visit (a page, or a record) with idempotent heartbeats.

    elapsed = wall clock since the visit started
    active  = visible AND focused AND recent input   (an *estimate*)
    idle    = elapsed - active
    """
    _name = 'adoption.active.session'
    _inherit = ['adoption.immutable.mixin']
    _description = 'Adoption Active Session (timed visit)'
    _order = 'started_at desc, id desc'

    user_id = fields.Many2one('res.users', string='User', index=True, ondelete='set null')
    company_id = fields.Many2one('res.company', index=True, ondelete='set null')
    session_key = fields.Char(required=True, help='Client-generated visit id.')
    browser_session = fields.Char(index=True, help='One per browser tab session.')
    kind = fields.Selection([
        ('record', 'Record'), ('list', 'List / kanban'), ('form_new', 'Unsaved form'),
        ('analysis', 'Report / analysis'), ('dashboard', 'Dashboard'),
        ('client', 'Other screen'), ('other', 'Other'),
    ], string='Screen Type',default='other', index=True)
    model_name = fields.Char(string='Model', index=True)
    record_id = fields.Integer(string='Record ID')
    record_name = fields.Char(string='Record')
    view_type = fields.Char()
    action_identifier = fields.Char()
    page_name = fields.Char()
    started_at = fields.Datetime(required=True, index=True)
    last_beat_at = fields.Datetime()
    ended_at = fields.Datetime()
    activity_date = fields.Date(required=True, index=True)
    elapsed_seconds = fields.Integer(string='Total Seconds')
    active_seconds = fields.Integer()
    idle_seconds = fields.Integer(compute='_compute_idle')
    heartbeat_count = fields.Integer()
    last_seq = fields.Integer(default=-1)
    state = fields.Selection([('open', 'Open'), ('closed', 'Closed'), ('stale', 'Stale')],
                             default='open', index=True)

    if _compat.HAS_CONSTRAINT:
        _key_uniq = models.Constraint('UNIQUE(user_id, session_key)', 'Duplicate visit.')
    else:
        _sql_constraints = [('key_uniq', 'unique(user_id, session_key)', 'Duplicate visit.')]

    @api.depends('elapsed_seconds', 'active_seconds')
    def _compute_idle(self):
        for rec in self:
            rec.idle_seconds = session_math.idle_seconds(rec.elapsed_seconds, rec.active_seconds)

    @api.model
    def _cron_close_stale(self):
        """A tab that was closed without a final heartbeat (crash, suspend,
        network loss) stays 'open' forever otherwise.  Close it at its last
        heartbeat so no time is invented after the connection was lost."""
        minutes = self.env['adoption.settings']._runtime()['stale_minutes']
        limit = fields.Datetime.now() - timedelta(minutes=minutes)
        stale = self.sudo().with_context(adoption_internal=True).search(
            [('state', '=', 'open'), ('last_beat_at', '<', limit)], limit=10000)
        for session in stale:
            session.write({'state': 'stale', 'ended_at': session.last_beat_at})
        return len(stale)
