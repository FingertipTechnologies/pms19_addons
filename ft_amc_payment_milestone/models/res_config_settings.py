# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .project_custom_milestone import DEFAULT_SEND_DAY, PARAM_SEND_DAY


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # One day for both automatic sends (scheduled action "AMC: Send Monthly
    # Timesheets & Milestones"): the AMC timesheet / task reports
    # (ft_amc_monthly_timesheet, which reads it through
    # ft.amc.monthly.report._send_from_day) and the AMC payment milestones.
    amc_milestone_send_day = fields.Integer(
        string='AMC Monthly E-mail Day', config_parameter=PARAM_SEND_DAY,
        default=DEFAULT_SEND_DAY,
        help="Day of the month (1-28) on which the previous month's AMC "
             "timesheet / task reports AND the AMC payment milestones that are "
             "still Not Started (with their send switch on) are e-mailed to the "
             "customers, in one scheduled action.")

    @api.constrains('amc_milestone_send_day')
    def _check_amc_milestone_send_day(self):
        for settings in self:
            if not 1 <= settings.amc_milestone_send_day <= 28:
                raise ValidationError(_(
                    "The AMC monthly e-mail day must be between 1 and 28 so it "
                    "exists in every month."))
