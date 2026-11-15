from odoo import _, api, fields, models
from odoo.exceptions import UserError


class FtPmsDailyReportLog(models.Model):
    """One row per (recipient, day): the dedupe of the daily e-mail.

    Created before the e-mail is built, so a failure (no e-mail address,
    rendering error, mail queue exception) stays visible and can be retried
    from the list; the unique constraint guarantees a person never gets the
    same day's report twice unless somebody forces it from the wizard.
    """
    _name = 'ft.pms.daily.report.log'
    _description = 'PMS Daily Status Report Log'
    _order = 'report_date desc, id desc'

    user_id = fields.Many2one(
        'res.users', string='Recipient', required=True, index=True,
        ondelete='cascade', readonly=True)
    email = fields.Char(related='user_id.email', string='E-mail')
    report_date = fields.Date(string='Report Date', required=True, index=True, readonly=True)
    state = fields.Selection([
        ('queued', 'Queued'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    ], string='Status', default='queued', required=True, index=True, readonly=True)
    mail_id = fields.Many2one('mail.mail', string='Email', ondelete='set null', readonly=True)
    mail_state = fields.Selection(related='mail_id.state', string='Email Status')
    error = fields.Text(string='Error', readonly=True)
    sent_on = fields.Datetime(string='Sent On', readonly=True)
    implementation_count = fields.Integer(string='Implementation Projects', readonly=True)
    amc_task_count = fields.Integer(string='AMC Tasks', readonly=True)
    attachment_ids = fields.One2many(
        'ir.attachment', 'res_id', string='Attachments', readonly=True,
        domain=[('res_model', '=', 'ft.pms.daily.report.log')])

    _unique_user_date = models.Constraint(
        'unique(user_id, report_date)',
        'A daily status report is already logged for this recipient and day.')

    @api.depends('user_id', 'report_date')
    def _compute_display_name(self):
        for log in self:
            log.display_name = "%s - %s" % (
                fields.Date.to_string(log.report_date) if log.report_date else '',
                log.user_id.name or '')

    # ------------------------------------------------------------------
    # Mail queue follow-up
    # ------------------------------------------------------------------
    def _sync_mail_state(self):
        """Copy the outcome of the mail queue onto queued logs."""
        for log in self.filtered(lambda l: l.state == 'queued'):
            mail = log.mail_id.sudo()
            if not mail:
                continue
            if mail.state == 'sent':
                log.write({'state': 'sent', 'sent_on': fields.Datetime.now(), 'error': False})
            elif mail.state in ('exception', 'cancel'):
                log.write({
                    'state': 'failed',
                    'error': mail.failure_reason or mail.failure_type
                    or _('The e-mail could not be delivered.'),
                })

    # ------------------------------------------------------------------
    # Buttons / server action
    # ------------------------------------------------------------------
    def action_sync_mail_state(self):
        self.sudo()._sync_mail_state()
        return True

    def action_retry_failed(self):
        """Rebuild and resend the report of the FAILED logs in the selection.

        The figures are always today's (the dashboards have no history), so
        only today's logs can be retried; a past day's failure is kept as a
        record and cannot be re-sent.
        """
        Report = self.env['ft.pms.daily.report']
        today = Report._report_date()
        failed = self.filtered(lambda l: l.state == 'failed')
        if not failed:
            raise UserError(_("Select at least one failed report."))
        past = failed.filtered(lambda l: l.report_date != today)
        if past:
            raise UserError(_(
                "Only today's reports (%s) can be retried; the data of a past "
                "day cannot be rebuilt. Past logs: %s",
                fields.Date.to_string(today),
                ', '.join(past.mapped('display_name'))))
        Report.send_daily_reports(
            users=failed.mapped('user_id'), force=True, report_date=today,
            force_send=True)
        return True
