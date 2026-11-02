# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .project_custom_milestone import DEFAULT_SEND_DAY, PARAM_SEND_DAY


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    amc_milestone_send_day = fields.Integer(
        string='AMC Milestone E-mail Day', config_parameter=PARAM_SEND_DAY,
        default=DEFAULT_SEND_DAY,
        help="Day of the month on which the previous month's AMC milestones "
             "that are still Not Started (with their send switch on) are marked "
             "Completed and e-mailed to the customer (1-28).")

    @api.constrains('amc_milestone_send_day')
    def _check_amc_milestone_send_day(self):
        for settings in self:
            if not 1 <= settings.amc_milestone_send_day <= 28:
                raise ValidationError(_(
                    "The AMC milestone e-mail day must be between 1 and 28 so it "
                    "exists in every month."))
