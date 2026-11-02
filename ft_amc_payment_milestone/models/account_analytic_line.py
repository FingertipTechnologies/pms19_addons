# -*- coding: utf-8 -*-
from odoo import models


class AccountAnalyticLine(models.Model):
    """project_date_extension refuses a timesheet dated after the due date of
    the milestone its task is attached to (a stage cut-off). An AMC monthly
    milestone is not a stage: its due date is the last day of the billing
    month, and a task deployed in December may legitimately carry October
    and November lines (requirement 49). The cut-off is therefore skipped for
    lines whose task sits on an AMC monthly milestone; every other milestone
    keeps the check untouched."""

    _inherit = 'account.analytic.line'

    def _ft_check_milestone_timesheet_date(self):
        lines = self.filtered(
            lambda line: not line.task_id.custom_milestone_id.sudo().is_amc_monthly)
        return super(AccountAnalyticLine, lines)._ft_check_milestone_timesheet_date()
