from datetime import datetime, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

DEFAULT_DAILY_REPORT_EMAIL_FROM = 'Support Fingertip <support@fingertipplus.com>'
CRON_XMLID = 'ft_pms_daily_status_report.ir_cron_send_daily_reports'


class ResCompany(models.Model):
    _inherit = 'res.company'

    daily_report_email_from = fields.Char(
        string='Daily Report Sender', default=DEFAULT_DAILY_REPORT_EMAIL_FROM,
        help="Sender (and reply-to) of the daily project status e-mail.")
    daily_report_send_hour = fields.Float(
        string='Daily Report Send Time', default=8.0,
        help="Time of day (company time zone) at which the daily project "
             "status e-mails are sent. The cron follows the main company.")
    daily_report_xlsx_row_limit = fields.Integer(
        string='Daily Report Excel Row Limit', default=50,
        help="When the Implementation or AMC table of an e-mail has more "
             "rows than this, the table is attached as an Excel file and "
             "the body keeps a summary only.")

    @api.constrains('daily_report_send_hour', 'daily_report_xlsx_row_limit')
    def _check_daily_report_settings(self):
        for company in self:
            if not 0.0 <= company.daily_report_send_hour < 24.0:
                raise ValidationError(_(
                    "The daily report send time must be between 00:00 and 23:59."))
            if company.daily_report_xlsx_row_limit < 1:
                raise ValidationError(_(
                    "The daily report Excel row limit must be at least 1."))

    def write(self, vals):
        res = super().write(vals)
        if 'daily_report_send_hour' in vals:
            self._ft_daily_report_reschedule_cron()
        return res

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _ft_daily_report_email_from(self):
        self.ensure_one()
        return self.daily_report_email_from or DEFAULT_DAILY_REPORT_EMAIL_FROM

    def _ft_daily_report_tz(self):
        self.ensure_one()
        return pytz.timezone(self.partner_id.tz or self.env.user.tz or 'UTC')

    def _ft_daily_report_next_call(self, now=None):
        """Next occurrence of the send hour (company tz) as a naive UTC
        datetime, strictly after ``now``."""
        self.ensure_one()
        tz = self._ft_daily_report_tz()
        now = now or datetime.utcnow()
        local_now = pytz.utc.localize(now).astimezone(tz)
        value = self.daily_report_send_hour or 0.0
        hour = min(int(value), 23)
        minute = min(int(round((value - int(value)) * 60)), 59)
        naive = local_now.replace(tzinfo=None).replace(
            hour=hour, minute=minute, second=0, microsecond=0)
        candidate = tz.localize(naive)
        if candidate <= local_now:
            candidate = tz.localize(naive + timedelta(days=1))
        return candidate.astimezone(pytz.utc).replace(tzinfo=None)

    def _ft_daily_report_reschedule_cron(self):
        """Move the daily cron's nextcall to the main company's send hour.

        There is one cron for the whole database, so its schedule follows
        the main company (base.main_company); other companies' hour settings
        are kept but do not move it.
        """
        cron = self.env.ref(CRON_XMLID, raise_if_not_found=False)
        if not cron:
            return
        main = self.env.ref('base.main_company', raise_if_not_found=False)
        company = main if main and main in self else (main or self[:1])
        if not company:
            return
        cron.sudo().write({'nextcall': company._ft_daily_report_next_call()})
