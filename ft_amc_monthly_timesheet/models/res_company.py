from odoo import fields, models

DEFAULT_AMC_REPORT_EMAIL_FROM = 'Support Fingertip <support@fingertipplus.com>'
PARAM_EMAIL_FROM = 'ft_amc_monthly_timesheet.email_from'
PARAM_START_MONTH = 'ft_amc_monthly_timesheet.start_month'


class ResCompany(models.Model):
    _inherit = 'res.company'

    # Settings live in ir.config_parameter (no res.company columns), so the
    # module code can run on a database that has not been upgraded yet.

    def _amc_report_email_from(self):
        return (self.env['ir.config_parameter'].sudo().get_param(PARAM_EMAIL_FROM)
                or DEFAULT_AMC_REPORT_EMAIL_FROM)

    def _amc_report_start_month(self):
        value = self.env['ir.config_parameter'].sudo().get_param(PARAM_START_MONTH)
        return fields.Date.to_date(value) if value else False
