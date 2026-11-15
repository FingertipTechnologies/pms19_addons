from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    daily_report_email_from = fields.Char(
        related='company_id.daily_report_email_from', readonly=False)
    daily_report_send_hour = fields.Float(
        related='company_id.daily_report_send_hour', readonly=False)
    daily_report_xlsx_row_limit = fields.Integer(
        related='company_id.daily_report_xlsx_row_limit', readonly=False)
