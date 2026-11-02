from odoo import _, fields, models
from odoo.exceptions import UserError

from .periods import month_end, month_start, previous_month


class ProjectProject(models.Model):
    _inherit = 'project.project'

    amc_report_enabled = fields.Boolean(
        string='Send monthly AMC timesheet', default=True, copy=False,
        help="Email the approved timesheet of the previous month to the customer "
             "on/after the 5th of every month (AMC projects only).")
    amc_recipient_ids = fields.Many2many(
        'res.partner', 'ft_amc_project_recipient_rel', 'project_id', 'partner_id',
        string='Additional report recipients',
        help="Contacts emailed in addition to the project customer and the POC email.")
    amc_report_ids = fields.One2many(
        'ft.amc.monthly.report', 'project_id', string='AMC Monthly Reports')
    amc_report_count = fields.Integer(
        string='AMC Reports', compute='_compute_amc_report_count')

    def _compute_amc_report_count(self):
        # sudo: the smart button is rendered for every project user, while
        # the report model itself is restricted to AMC managers.
        counts = dict(self.env['ft.amc.monthly.report'].sudo()._read_group(
            [('project_id', 'in', self.ids)], ['project_id'], ['__count']))
        for project in self:
            project.amc_report_count = counts.get(project._origin, 0)

    def action_view_amc_reports(self):
        self.ensure_one()
        self.env['ft.amc.monthly.report']._check_manager()
        return {
            'type': 'ir.actions.act_window',
            'name': _('AMC Monthly Timesheets'),
            'res_model': 'ft.amc.monthly.report',
            'view_mode': 'list,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }

    def _amc_contract_covers(self, period_start):
        """Whether the contract dates overlap the month starting ``period_start``."""
        self.ensure_one()
        if not self.date_start:
            return False
        return self.date_start <= month_end(period_start) and (
            not self.date or self.date >= period_start)

    def _amc_default_report_month(self):
        """First day of the month the Generate wizard proposes.

        The previous calendar month when the contract covers it (the month the
        cron sends), else the current month when covered (a contract that
        started this month), else the contract's first month.
        """
        self.ensure_one()
        Report = self.env['ft.amc.monthly.report']
        today = Report._local_today(self.company_id or self.env.company)
        previous, _end = previous_month(today)
        for candidate in (previous, month_start(today)):
            if self._amc_contract_covers(candidate):
                return candidate
        return month_start(self.date_start) if self.date_start else previous

    def action_amc_open_generate_wizard(self):
        """Project tab button: choose the month, then build (no email) its report."""
        self.ensure_one()
        self.env['ft.amc.monthly.report']._check_manager()
        if self.ft_project_type != 'amc':
            raise UserError(_("Monthly timesheet reports are only available on AMC projects."))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generate AMC Monthly Timesheet'),
            'res_model': 'ft.amc.report.generate.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_project_id': self.id},
        }

    def _amc_generate_month(self, period_start):
        """Build (no email) the report of the month starting ``period_start`` and open it."""
        self.ensure_one()
        Report = self.env['ft.amc.monthly.report']
        Report._check_manager()
        if self.ft_project_type != 'amc':
            raise UserError(_("Monthly timesheet reports are only available on AMC projects."))
        company = self.company_id or self.env.company
        report = Report.with_company(company)._get_or_create(self, period_start)
        if report.state in ('draft', 'failed', 'no_data'):
            report.action_generate()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'ft.amc.monthly.report',
            'res_id': report.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_amc_generate_previous_month(self):
        """Build (no email) the previous month's report and open it."""
        self.ensure_one()
        company = self.company_id or self.env.company
        today = self.env['ft.amc.monthly.report']._local_today(company)
        period_start, _period_end = previous_month(today)
        return self._amc_generate_month(period_start)
