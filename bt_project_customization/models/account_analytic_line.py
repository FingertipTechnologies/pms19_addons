from odoo import models, fields, api


class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    ft_is_rework = fields.Boolean(
        string='Rework',
        default=False,
        readonly=True,
        copy=False,
        index=True,
        help="Set when this time was logged on a task that had already been "
             "delivered and moved back out of a completed stage. It is the "
             "second (or later) round of effort on work that was once called "
             "finished, and is what the Rework Hours figures count.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Stamp the rework flag from the task's state AT THE TIME OF ENTRY.

        Decided on creation and then left alone, rather than computed from the
        task later, because it is a fact about when the work happened. A task
        reopened next month must not retroactively turn this month's hours into
        rework, and the first round of effort on a task that was later reopened
        was not rework either — only what came after the reopen was.
        """
        Task = self.env['project.task']
        for vals in vals_list:
            if vals.get('ft_is_rework'):
                # Explicitly supplied (imports, corrections): leave it alone.
                continue
            task_id = vals.get('task_id')
            if not task_id:
                continue
            # sudo: ft_reopen_count is readonly to users and not every timesheet
            # author can read the task's tracked fields.
            task = Task.sudo().browse(task_id)
            vals['ft_is_rework'] = bool(task.ft_reopen_count)
        return super().create(vals_list)
