"""Generate (preview) the monthly AMC report of a project for a chosen month.

The project tab used to build only the previous calendar month. A contract
that started this month has nothing in the previous one (and the generation
is refused because the contract does not cover it), while the month that does
hold approved timesheets could not be reached at all. The wizard lets the
manager pick the month; the project proposes the most sensible one.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.periods import month_start


class AmcReportGenerateWizard(models.TransientModel):
    _name = 'ft.amc.report.generate.wizard'
    _description = 'Generate AMC Monthly Timesheet Report'

    project_id = fields.Many2one(
        'project.project', string='Project', required=True, readonly=True,
        ondelete='cascade')
    contract_start = fields.Date(related='project_id.date_start', string='Contract Start')
    contract_end = fields.Date(related='project_id.date', string='Contract End')
    month = fields.Date(
        string='Month', required=True,
        help="Any day of the month to report: the whole calendar month is taken.")
    period_label = fields.Char(compute='_compute_period_label', string='Reporting Month')

    @api.depends('month')
    def _compute_period_label(self):
        for wizard in self:
            wizard.period_label = wizard.month.strftime('%B %Y') if wizard.month else ''

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        project_id = res.get('project_id') or self.env.context.get('default_project_id')
        if project_id and 'month' in fields_list and not res.get('month'):
            project = self.env['project.project'].browse(project_id)
            res['month'] = project._amc_default_report_month()
        return res

    def action_confirm(self):
        self.ensure_one()
        period_start = month_start(self.month)
        project = self.project_id
        if not project._amc_contract_covers(period_start):
            raise UserError(_(
                "The AMC contract of project '%(project)s' (%(start)s - %(end)s) does not "
                "cover %(period)s.",
                project=project.display_name, start=project.date_start or _('not set'),
                end=project.date or _('open'), period=period_start.strftime('%B %Y')))
        return project._amc_generate_month(period_start)
