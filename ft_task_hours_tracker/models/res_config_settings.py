from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    ft_default_task_time_limit = fields.Float(
        string='Time Limit (Hours)',
        config_parameter='ft_task_hours_tracker.default_time_limit',
        help='Default maximum hours allowed per task across all projects. Set to 0 to disable.',
    )
