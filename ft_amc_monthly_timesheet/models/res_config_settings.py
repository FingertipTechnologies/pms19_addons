from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .res_company import DEFAULT_AMC_REPORT_EMAIL_FROM, PARAM_EMAIL_FROM, PARAM_START_MONTH


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    amc_report_email_from = fields.Char(
        string='AMC Report Sender', config_parameter=PARAM_EMAIL_FROM,
        default=DEFAULT_AMC_REPORT_EMAIL_FROM)
    # Date fields cannot use config_parameter=; stored by get_values/set_values.
    amc_report_start_month = fields.Date(string='AMC Reporting Start Month')

    @api.model
    def get_values(self):
        res = super().get_values()
        res['amc_report_start_month'] = self.env.company._amc_report_start_month()
        return res

    def set_values(self):
        super().set_values()
        for settings in self:
            start_month = settings.amc_report_start_month
            if start_month and start_month.day != 1:
                raise ValidationError(_(
                    "The AMC reporting start month must be the first day of a month."))
            self.env['ir.config_parameter'].sudo().set_param(
                PARAM_START_MONTH, fields.Date.to_string(start_month) if start_month else False)
