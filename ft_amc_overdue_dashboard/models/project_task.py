from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ProjectTask(models.Model):
    """Frozen "overdue at completion" figure and the original-deadline lock.

    Both are generic task behaviour (every project type gets them, which is
    harmless), but only the AMC Task Overdue Dashboard reads
    ``ft_historical_overdue_days``: it is the number the dashboard shows for a
    completed task so that a task finished seven days late in September still
    reads "7" in October, however often it is viewed.
    """
    _inherit = 'project.task'

    ft_historical_overdue_days = fields.Integer(
        string='Overdue at Completion (Days)', readonly=True, copy=False,
        help='Calendar days between the ORIGINAL deadline (the first one the '
             'task was given, not the latest revision) and the day the task '
             'was completed. Stamped when the task is completed and never '
             'changed afterwards; 0 when the task was completed on time or '
             'had no deadline. Recomputed only if the task is reopened and '
             'completed again. Read by the AMC Task Overdue Dashboard.')

    # Vals keys whose write can turn a task into a completed one (or re-date
    # its completion), after which the frozen figure is (re)stamped.
    _FT_AMC_FREEZE_TRIGGERS = ('stage_id', 'state', 'date_end')
    # States whose tasks carry a frozen figure. 1_deployed: Deployed,
    # ft_amc_payment_milestone, counts as done - a deployed task was frozen
    # when it became Done, so it is only re-stamped when its completion is
    # explicitly re-dated (date_end), never by the state write that deploys it.
    _FT_AMC_FROZEN_STATES = ('1_done', '1_deployed')

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def ft_overdue_reference_deadline(self):
        """The deadline overdue is measured from: the original one.

        ``pwf_original_deadline`` (ft_pms_planning_workflow) is the first
        deadline the task was given and is never overwritten; the current
        ``date_deadline`` is only a fallback for tasks created before deadline
        tracking that the install hook could not backfill.
        """
        self.ensure_one()
        return self.pwf_original_deadline or self.date_deadline

    def _ft_amc_overdue_days_between(self, deadline, end):
        """Whole local calendar days from ``deadline`` to ``end`` (>= 0).

        Both are UTC Datetimes; they are converted to the calendar of the
        environment's timezone (context ``tz``, else the user's) through
        ``_ft_local_date`` so an evening deadline is judged by the right day.
        0 when either side is missing or ``end`` is not after the deadline.
        """
        deadline_day = self._ft_local_date(deadline)
        end_day = self._ft_local_date(end)
        if not deadline_day or not end_day:
            return 0
        return max((end_day - deadline_day).days, 0)

    def _ft_amc_freeze_overdue(self, states=('1_done',)):
        """Stamp ``ft_historical_overdue_days`` on the completed tasks in self.

        Only tasks whose ``state`` is in ``states`` (default: ``1_done``) are
        touched (cancelled and open tasks keep whatever they carry; a
        Deployed task, ``1_deployed``, keeps the figure frozen when it was
        Done unless the caller asks for it, see write()). The figure is the
        local-day distance from the original deadline to ``date_end`` (now,
        when the stage move left it unset), floored at 0. Written through
        ``super().write`` as sudo, and only when the value actually changes,
        so completing a task costs at most one extra UPDATE and never
        re-enters this module's write() hooks.
        """
        by_value = {}
        for task in self:
            if task.state not in states:
                continue
            days = task._ft_amc_overdue_days_between(
                task.ft_overdue_reference_deadline(),
                task.date_end or fields.Datetime.now())
            if days != (task.ft_historical_overdue_days or 0):
                by_value.setdefault(days, self.browse())
                by_value[days] |= task
        for days, tasks in by_value.items():
            super(ProjectTask, tasks.sudo()).write(
                {'ft_historical_overdue_days': days})

    def _ft_amc_check_original_deadline_lock(self, vals):
        """Refuse to change an original deadline that is already set.

        The field is read-only in the UI, but readonly is only a form hint:
        an RPC ``write`` would still get through. The superuser is exempt
        (ft_pms_planning_workflow sets the field itself through sudo, and
        the install hook backfills it in SQL); everybody else may only fill
        an EMPTY original deadline, which is what the lazy first-set in
        ft_pms_planning_workflow needs.
        """
        if 'pwf_original_deadline' not in vals or self.env.su:
            return
        new_value = fields.Datetime.to_datetime(vals['pwf_original_deadline'] or False)
        for task in self:
            current = task.pwf_original_deadline
            if current and current != new_value:
                raise UserError(_(
                    "The Original Deadline of \"%(task)s\" is already set "
                    "(%(value)s) and cannot be changed: overdue days are "
                    "measured from it. Change the Deadline instead.",
                    task=task.display_name,
                    value=fields.Datetime.to_string(current),
                ))

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        tasks = super().create(vals_list)
        # A task raised straight into a final stage is completed the moment
        # it exists (bt_project_customization stamps state = 1_done in its
        # own create). Its frozen figure is stamped here as well, after every
        # dependency's create ran, so pwf_original_deadline is already set.
        tasks._ft_amc_freeze_overdue()
        return tasks

    def write(self, vals):
        self._ft_amc_check_original_deadline_lock(vals)
        res = super().write(vals)
        # After super(): bt_project_customization stamps state / date_end on
        # a move into a final stage inside ITS write (through a nested sudo
        # write that re-enters here with 'state' and 'date_end' in vals), so
        # by now the task is 1_done whichever of the three keys triggered.
        # A reopened task (state back to in progress) is left alone and keeps
        # the figure of its last completion until it is completed again.
        # A Deployed task (1_deployed) is only re-stamped when its completion
        # is re-dated: the state write that deploys / undeploys it must not
        # move a figure that was frozen when the task became Done.
        if any(key in vals for key in self._FT_AMC_FREEZE_TRIGGERS):
            self._ft_amc_freeze_overdue(
                self._FT_AMC_FROZEN_STATES if 'date_end' in vals else ('1_done',))
        return res
