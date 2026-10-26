from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Context key the Task Planner sets on its own task write: move_task_week
# logs the move itself (with from/to week and reason), so the generic
# deadline-change logging below must not add a second row for it.
SKIP_LOG_KEY = 'pwf_skip_deadline_log'
# Context keys a caller can set to describe a deadline change.
REASON_KEY = 'ft_deadline_change_reason'
REOPEN_KEY = 'ft_reopen_via_wizard'


class FtPmsTaskWeekMove(models.Model):
    """Deadline tracking log of a task (all task types).

    One row per deadline change:
    * ``week_move``: week re-allocation from the Task Planner
      (ft.pms.planner.move_task_week);
    * ``deadline_change``: any other change of the deadline (form edit,
      Kanban week drag, import, ...);
    * ``reopen``: deadline set while reopening a completed task for rework.

    Read-only: rows are written as superuser only by the planner and by the
    project.task write() override below.
    """
    _name = 'ft.pms.task.week.move'
    _description = 'Task Deadline Change'
    _order = 'moved_on desc, id desc'
    _rec_name = 'task_id'

    task_id = fields.Many2one(
        'project.task', string='Task', required=True, index=True,
        ondelete='cascade', readonly=True)
    project_id = fields.Many2one(
        related='task_id.project_id', string='Project', store=True,
        readonly=True)
    from_week_id = fields.Many2one(
        'qa_testapp.sprint', string='From Week', ondelete='set null',
        readonly=True)
    to_week_id = fields.Many2one(
        'qa_testapp.sprint', string='To Week', ondelete='set null',
        readonly=True)
    change_type = fields.Selection(
        [('week_move', 'Week Move (Planner)'),
         ('deadline_change', 'Deadline Change'),
         ('reopen', 'Reopened for Rework')],
        string='Change Type', required=True, default='week_move',
        readonly=True, index=True)
    reason = fields.Text(string='Reason', readonly=True)
    user_id = fields.Many2one(
        'res.users', string='Changed By', readonly=True,
        default=lambda self: self.env.user)
    moved_on = fields.Datetime(
        string='Changed On', readonly=True, default=fields.Datetime.now)
    deadline_at_move = fields.Datetime(
        string='Old Deadline', readonly=True,
        help='Task deadline just before the change.')
    new_deadline = fields.Datetime(
        string='New Deadline', readonly=True,
        help='Task deadline after the change.')

    def write(self, vals):
        if not self.env.su:
            raise UserError(_('Week move log entries cannot be modified.'))
        return super().write(vals)

    def unlink(self):
        if not self.env.su:
            raise UserError(_('Week move log entries cannot be deleted.'))
        return super().unlink()


class ProjectTask(models.Model):
    _inherit = 'project.task'

    pwf_week_move_ids = fields.One2many(
        'ft.pms.task.week.move', 'task_id', string='Deadline Changes',
        readonly=True)
    pwf_original_deadline = fields.Datetime(
        string='Original Deadline', readonly=True, copy=False,
        help='First deadline the task was given (or the deadline before its '
             'first change, for tasks created before deadline tracking). '
             'Set once, never overwritten.')

    @api.model_create_multi
    def create(self, vals_list):
        tasks = super().create(vals_list)
        # The deadline may be filled by other modules during create (e.g.
        # from the Week), so read it back instead of trusting vals.
        for task in tasks:
            if task.date_deadline and not task.pwf_original_deadline:
                task.sudo().with_context(**{SKIP_LOG_KEY: True}).write(
                    {'pwf_original_deadline': task.date_deadline})
        return tasks

    def write(self, vals):
        # A Week change re-dates the task (ft_sprint_management), so it is
        # tracked as well; the actual before/after comparison decides.
        track = (('date_deadline' in vals or 'sprint_id' in vals)
                 and not self.env.context.get(SKIP_LOG_KEY))
        if not track:
            return super().write(vals)
        before = {
            task.id: (task.date_deadline, task.sprint_id.id,
                      task.pwf_original_deadline)
            for task in self
        }
        res = super().write(vals)
        self._pwf_log_deadline_changes(before)
        return res

    def _pwf_log_deadline_changes(self, before):
        ctx = self.env.context
        reason = (ctx.get(REASON_KEY) or '').strip() or False
        change_type = (
            'reopen' if (ctx.get(REOPEN_KEY)
                         or (reason and reason.startswith('Reopened')))
            else 'deadline_change')
        now = fields.Datetime.now()
        log_vals = []
        for task in self:
            if task.id not in before:
                continue
            old_deadline, old_week_id, original = before[task.id]
            new_deadline = task.date_deadline
            if old_deadline == new_deadline:
                continue
            if not original:
                # First known deadline: the one before this change, or the
                # new one when the deadline is being set for the first time.
                task.sudo().with_context(**{SKIP_LOG_KEY: True}).write(
                    {'pwf_original_deadline': old_deadline or new_deadline})
            if not old_deadline:
                # Initial set, not a change.
                continue
            log_vals.append({
                'task_id': task.id,
                'change_type': change_type,
                'from_week_id': old_week_id or False,
                'to_week_id': task.sprint_id.id or False,
                'reason': reason,
                'user_id': self.env.user.id,
                'moved_on': now,
                'deadline_at_move': old_deadline,
                'new_deadline': new_deadline,
            })
        if log_vals:
            # sudo: the log has no create ACL; the task write already passed
            # the user's access checks.
            self.env['ft.pms.task.week.move'].sudo().create(log_vals)
