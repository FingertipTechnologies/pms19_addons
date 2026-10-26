from odoo import api, fields, models


class FtTaskReopenWizard(models.TransientModel):
    """Reopen a completed task for rework with a new, future deadline.

    The only way out of a final stage for a normal user (see
    project.task._check_reopen_via_wizard). Reserved to the project's PM, a
    PM / Project Coordinator job, or an Administrator. All checks and the
    write live on the task (_ft_reopen_for_rework), so the rule is stated once.
    """
    _name = 'ft.task.reopen.wizard'
    _description = 'Reopen Task for Rework'

    task_id = fields.Many2one(
        'project.task', string='Task', required=True, readonly=True,
        ondelete='cascade')
    current_deadline = fields.Datetime(
        related='task_id.date_deadline', string='Current Deadline')
    new_deadline = fields.Datetime(string='New Deadline', required=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        task_id = res.get('task_id') or self.env.context.get('default_task_id')
        if task_id:
            # Refuse to even open the dialog for somebody who may not reopen.
            task = self.env['project.task'].browse(task_id)
            task._ft_check_reopen_permission()
            # A same-day type is reopened for today (see
            # project.task._ft_validate_reopen_deadline): offer that.
            if ('new_deadline' in fields_list and not res.get('new_deadline')
                    and task._ft_requires_same_day_deadline(task.task_type)):
                res['new_deadline'] = task._ft_today_end_utc()
        return res

    def action_confirm(self):
        self.ensure_one()
        self.task_id._ft_reopen_for_rework(self.new_deadline)
        return {'type': 'ir.actions.act_window_close'}
