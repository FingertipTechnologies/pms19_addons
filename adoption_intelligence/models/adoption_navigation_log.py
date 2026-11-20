# -*- coding: utf-8 -*-
from odoo import fields, models

from . import _compat


class AdoptionNavigationLog(models.Model):
    """What the web client reports having *opened*.  This is browser telemetry:
    it proves a view was displayed, not that the user read it, and it is never
    used as evidence that a database operation succeeded."""
    _name = 'adoption.navigation.log'
    _inherit = ['adoption.immutable.mixin']
    _description = 'Adoption Navigation Log'
    _order = 'navigation_datetime desc, id desc'

    user_id = fields.Many2one('res.users', string='User', index=True, ondelete='set null')
    company_id = fields.Many2one('res.company', index=True, ondelete='set null')
    event_key = fields.Char(required=True, help='Client-generated id; makes ingestion idempotent.')
    event_type = fields.Selection([
        ('session_start', 'Session start'), ('page_view', 'Page view'),
        ('record_view', 'Record view'), ('list_view', 'List / kanban view'),
        ('report_view', 'Report / analysis view'), ('dashboard_view', 'Dashboard view'),
        ('search', 'Search / filter'), ('action_click', 'Action attempted'),
    ],string='Event Type', required=True, index=True)
    model_name = fields.Char(string='Model', index=True)
    record_id = fields.Integer(string='Record ID')
    record_name = fields.Char(string='Record')
    action_type = fields.Char(string='View type')
    action_identifier = fields.Char(string='Action / page')
    page_name = fields.Char(string='Page title')
    session_identifier = fields.Char(string='Browser session', index=True)
    navigation_datetime = fields.Datetime(required=True, index=True, string='DateTime')
    activity_date = fields.Date(required=True, index=True, string='Date')

    if _compat.HAS_CONSTRAINT:
        _event_uniq = models.Constraint('UNIQUE(user_id, event_key)', 'Duplicate navigation event.')
    else:
        _sql_constraints = [('event_uniq', 'unique(user_id, event_key)', 'Duplicate navigation event.')]

    if _compat.HAS_INDEX:
        _user_date_idx = models.Index('(user_id, activity_date)')
    else:
        def init(self):
            _compat.ensure_index(self.env.cr, 'adoption_navigation_log_user_date_idx',
                                 self._table, ['user_id', 'activity_date'])
