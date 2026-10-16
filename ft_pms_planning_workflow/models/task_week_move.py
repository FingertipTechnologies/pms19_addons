from odoo import _, fields, models
from odoo.exceptions import UserError


class FtPmsTaskWeekMove(models.Model):
    """Audit log of week re-allocations done from the Task Planner.

    Read-only: rows are written (as superuser) only by
    ft.pms.planner.move_task_week, after the user's write access on the task
    has been checked.
    """
    _name = 'ft.pms.task.week.move'
    _description = 'Task Week Move'
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
    reason = fields.Text(string='Reason', readonly=True)
    user_id = fields.Many2one(
        'res.users', string='Moved By', readonly=True,
        default=lambda self: self.env.user)
    moved_on = fields.Datetime(
        string='Moved On', readonly=True, default=fields.Datetime.now)
    deadline_at_move = fields.Datetime(
        string='Deadline at Move', readonly=True,
        help='Task deadline just before it was moved.')
    new_deadline = fields.Datetime(
        string='New Deadline', readonly=True,
        help="Task deadline after the move: the target week's Sunday.")

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
        'ft.pms.task.week.move', 'task_id', string='Week Moves',
        readonly=True)
    pwf_original_deadline = fields.Datetime(
        string='Original Deadline', readonly=True, copy=False,
        help='Deadline the task had before it was first moved to another '
             'week from the Task Planner. Set once, never overwritten.')
