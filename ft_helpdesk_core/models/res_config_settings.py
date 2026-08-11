from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    helpdesk_portal_allow_close = fields.Boolean(
        string='Allow Portal Users to Close Tickets',
        config_parameter='ft_helpdesk.portal_allow_close',
        default=False,
    )
    helpdesk_portal_allow_reopen = fields.Boolean(
        string='Allow Portal Users to Reopen Tickets',
        config_parameter='ft_helpdesk.portal_allow_reopen',
        default=False,
    )
    helpdesk_auto_close_days = fields.Integer(
        string='Auto-Close Resolved Tickets After (Days)',
        config_parameter='ft_helpdesk.auto_close_days',
        default=7,
        help='Automatically close resolved tickets after this many days. 0 = disabled.',
    )
    helpdesk_default_team_id = fields.Many2one(
        'ft.helpdesk.team', string='Default Team',
        config_parameter='ft_helpdesk.default_team_id',
    )
    helpdesk_enable_kb_suggestions = fields.Boolean(
        string='Enable KB Suggestions on Ticket Creation',
        config_parameter='ft_helpdesk.enable_kb_suggestions',
        default=True,
    )
    helpdesk_enable_csat = fields.Boolean(
        string='Enable Customer Satisfaction Ratings',
        config_parameter='ft_helpdesk.enable_csat',
        default=False,
    )
