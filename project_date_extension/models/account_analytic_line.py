# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import _, api, models
from odoo.exceptions import UserError


class AccountAnalyticLine(models.Model):
    """Points 6 & 10: timesheet restriction honouring the extended date.

    A timesheet line whose task is tied to a custom milestone/stage
    (project.task.custom_milestone_id) may not be dated after that
    milestone's effective controlled date -
    ``milestone._ft_effective_deadline()`` - which is ``due_date`` onto
    which an approved Date Extension has already been written. That is
    exactly Point 10: when an approved extension exists the extended date
    is used automatically, with no separate lookup.

    Example (Point 10): DEV stage ends 10 Sep -> entries after 10 Sep are
    refused; once an extension to 15 Sep is approved, entries up to 15 Sep
    are accepted and only 16 Sep onward is refused.

    Only the superuser is exempt (imports, migrations, scheduled jobs).
    Date Extension Approvers are NOT exempt from this date rule: an admin
    who needs to log time past the date lifts the limit the same way
    everyone does - by approving an extension - so the control cannot be
    silently bypassed. (To exempt approvers instead, re-add the
    ``has_group`` check below.)
    """

    _inherit = "account.analytic.line"

    def _ft_check_milestone_timesheet_date(self):
        if self.env.su:
            return
        for line in self:
            task = line.task_id
            milestone = task.custom_milestone_id if task else False
            if not milestone:
                continue
            # Point 10: the effective date already reflects any approved
            # extension (approval writes it onto due_date).
            deadline = milestone._ft_effective_deadline()
            if not deadline:
                continue
            entry_date = line.date
            if entry_date and entry_date > deadline:
                raise UserError(
                    _(
                        "Timesheets for the milestone/stage '%(milestone)s' "
                        "are only allowed up to %(limit)s, its approved "
                        "date. Your entry is dated %(entry)s.\n\n"
                        "If work continues past that date, raise a Date "
                        "Extension Request for this milestone and have it "
                        "approved first - once approved, entries up to the "
                        "new date are accepted automatically.",
                        milestone=milestone.display_name,
                        limit=deadline,
                        entry=entry_date,
                    )
                )

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._ft_check_milestone_timesheet_date()
        return lines

    def write(self, vals):
        res = super().write(vals)
        if {"date", "task_id", "unit_amount"} & set(vals):
            self._ft_check_milestone_timesheet_date()
        return res
