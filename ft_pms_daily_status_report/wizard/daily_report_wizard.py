from odoo import _, fields, models


class FtPmsDailyReportWizard(models.TransientModel):
    """Project > Configuration > Send Daily Status Report: send now, to
    everybody or to a few test recipients."""
    _name = 'ft.pms.daily.report.wizard'
    _description = 'Send PMS Daily Status Report Now'

    user_ids = fields.Many2many(
        'res.users', string='Recipients', domain=[('share', '=', False)],
        help="Leave empty to send to every Project Manager and Technical "
             "Lead holding a project in scope. Each recipient only ever gets "
             "their own projects.")
    force = fields.Boolean(
        string='Resend Even If Already Sent Today',
        help="Ignore the one-per-recipient-per-day check and send again.")

    def action_send(self):
        self.ensure_one()
        logs = self.env['ft.pms.daily.report'].send_daily_reports(
            users=self.user_ids or None, force=self.force, force_send=True)
        action = self.env['ir.actions.act_window']._for_xml_id(
            'ft_pms_daily_status_report.action_daily_report_log')
        action['domain'] = [('id', 'in', logs.ids)]
        action['context'] = {}
        if not logs:
            action['help'] = _(
                "<p class='o_view_nocontent_smiling_face'>Nothing to send</p>"
                "<p>Every recipient already received today's report (tick "
                "\"Resend\" to send it again) or no project is in scope.</p>")
        return action
