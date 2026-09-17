from odoo import _, api, fields, models

from .week_utils import hours_to_hhmm, local_day_bounds, monday_of

# Cards drawn per column before the rest are summarised as "+ N more". The
# stock Kanban paginates its columns for the same reason: a project with a
# thousand open tasks must not render a thousand cards into a form tab.
BOARD_COLUMN_LIMIT = 40


class ProjectTask(models.Model):
    _inherit = 'project.task'

    # Column name unchanged (see the docstring on qa_testapp.sprint): the label
    # is what moved from "Sprint" to "Week".
    sprint_id = fields.Many2one(
        'qa_testapp.sprint', string='Week',
        index='btree_not_null',
        ondelete='set null',
        group_expand='_read_group_sprint_ids',
        help="Week this task belongs to. Setting it moves the task's deadline "
             "to that week's Sunday.",
    )
    sprint_start_date = fields.Date(
        related='sprint_id.start_date', string='Week Start Date',
        store=True, readonly=True,
        help='Monday of the assigned week.',
    )
    sprint_end_date = fields.Date(
        related='sprint_id.end_date', string='Week End Date',
        store=True, readonly=True,
        help='Sunday of the assigned week — the day the deadline is set to.',
    )

    @api.model
    def _read_group_sprint_ids(self, sprints, domain):
        """Show every week the project has work in as a Kanban column.

        Without this only weeks that already hold a task get a column, so there
        is nowhere to drag a task that is being pushed out to a later week —
        the very thing the board exists for. Mirrors how core expands the stage
        columns, and keys off the same ``default_project_id`` the board action
        passes in, so the All Tasks views are unaffected.

        Weeks are shared across projects now, so the expansion is the project's
        own span (project._ft_board_weeks) rather than the weeks belonging to
        it — otherwise every week in the database would become a column. That
        span runs continuously, so a week with nothing due in it still gets its
        column and the numbering never skips, and it carries the current week
        and the ones coming up as well — the same weeks, from the same helper,
        as the project's Tasks tab, so the two boards cannot drift apart.

        web_read_group runs on a read-only cursor. _ensure_weeks only creates
        when a week is missing — the first read after a new week comes into
        range — and Odoo retries that one request read-write.
        """
        search_domain = [('id', 'in', sprints.ids)]
        project_id = self.env.context.get('default_project_id')
        if project_id:
            project = self.env['project.project'].browse(project_id)
            weeks = project._ft_board_weeks()
            search_domain = ['|', ('id', 'in', weeks.ids)] + search_domain
        return sprints.browse(sprints._search(search_domain, order=sprints._order))

    # ------------------------------------------------------------------
    # Board rendering
    # ------------------------------------------------------------------
    def _board_column(self, column_id, name, expanded=False, current=False,
                      final_stage_ids=None):
        """These tasks as one column of a task board.

        Shared by both boards — the week's columns are stages, the project's
        are weeks — so a card looks the same wherever it is drawn and there is
        one place to change what a card says.

        ``count`` is the true total while ``cards`` is capped, so a truncated
        column still reports its real size in the header. ``expanded`` lifts
        the cap for this one column: it is what clicking "+ N more" asks for,
        and it is per column because the person asked about THIS column, not
        for every column on the board to grow at once.

        ``current`` marks the one column the board opens on — the week today
        falls in. Always present in the payload, so the widget can test it
        without knowing which board it is drawing; only the project's week
        columns ever set it, since "this week" means nothing to a stage.

        ``final_stage_ids`` is taken once by the caller and handed to every
        column. It is a search, and a board has a column per stage or per
        week — asking again for each of them, and again for its cards, was a
        dozen identical queries on every board load.
        """
        shown = self if expanded else self[:BOARD_COLUMN_LIMIT]
        if final_stage_ids is None:
            final_stage_ids = self._ft_final_stage_ids()
        final_stage_ids = set(final_stage_ids)
        done = len(self.filtered(lambda t: t.stage_id.id in final_stage_ids))
        return {
            'id': column_id,
            'name': name,
            'current': current,
            'count': len(self),
            # Drives the bar under the column heading, the way the stock
            # Kanban's progressbar fills as a column's work is finished.
            'done_count': done,
            'progress': round(100.0 * done / len(self)) if self else 0,
            'estimated': hours_to_hhmm(sum(self.mapped('estimated'))),
            'cards': shown._board_cards(final_stage_ids),
            'more': len(self) - len(shown),
        }

    def _board_cards(self, final_stage_ids=None):
        """One JSON card per task, shaped like a stock Kanban record.

        The same pieces the project Kanban puts on a card — title, tags,
        assignee avatars, a relative deadline, the priority star — plus the two
        figures this PMS runs on, Estimated and Time Spent.

        ``done`` is taken from _ft_final_stage_ids, the PMS's own answer to "is
        this finished", NOT from ``state``. The stock card fades a record on
        state 1_done; nothing here ever sets that (moving to a stage named
        Completed actively resets state to In Progress), so a card would never
        fade. The stage is what this database completes work with.
        """
        today = fields.Date.context_today(self)
        if final_stage_ids is None:
            final_stage_ids = set(self._ft_final_stage_ids())
        return [{
            'id': task.id,
            'name': task.display_name,
            'stage': task.stage_id.display_name or '',
            # The muted second line, the way the All Tasks board shows the
            # project under the title. Both boards are already scoped to one
            # project, so the module is what actually varies between cards.
            'module': task.module_id.display_name if task.module_id else '',
            'project': task.project_id.display_name if task.project_id else '',
            'priority': int(task.priority or '0'),
            'done': task.stage_id.id in final_stage_ids,
            'assignees': [
                {'id': user.id, 'name': user.name} for user in task.user_ids
            ],
            'tags': [
                {'name': tag.display_name, 'color': tag.color}
                for tag in task.tag_ids
            ],
            'estimated': hours_to_hhmm(task.estimated),
            'actual': hours_to_hhmm(task.effective_hours),
            **task._board_deadline(today),
        } for task in self]

    def _board_deadline(self, today):
        """The deadline as the remaining_days widget words it.

        A bare date tells the reader nothing without them doing the arithmetic;
        "In 3 days" and "5 days ago" are the same information already read.
        Counted in the reader's timezone, like every other date comparison in
        this module — date_deadline is a UTC datetime, and 23:59 local is
        already tomorrow in UTC.
        """
        self.ensure_one()
        if not self.date_deadline:
            return {'deadline': '', 'late': False}
        day = self._ft_local_date(self.date_deadline)
        delta = (day - today).days
        if delta == 0:
            label = _('Today')
        elif delta == 1:
            label = _('Tomorrow')
        elif delta == -1:
            label = _('Yesterday')
        elif delta > 1:
            label = _('In %s days') % delta
        else:
            label = _('%s days ago') % -delta
        # Overdue is only worth flagging while there is still something to do
        # about it: a finished task carries its old deadline for ever and
        # colouring every one of them red says nothing.
        return {'deadline': label, 'late': delta < 0}

    # ------------------------------------------------------------------
    # Deadline follows the week
    # ------------------------------------------------------------------
    def _deadline_for_week(self, week):
        """End of the week's Sunday, in the reader's timezone.

        ``date_deadline`` is a Datetime, so a week's Sunday has to be given a
        time of day. It is the close of that day locally (23:59:59), never
        midnight: a deadline of "Sunday 00:00" is due before the Sunday has
        even started, and would be judged late by anything finished on the day
        the user actually means.
        """
        if not (week and week.end_date):
            return False
        return local_day_bounds(self.env, week.end_date, end_of_day=True)

    @api.onchange('sprint_id')
    def _onchange_sprint_id(self):
        # Show the new deadline in the form straight away, so picking a week is
        # visibly the same act as setting the deadline.
        deadline = self._deadline_for_week(self.sprint_id)
        if deadline:
            self.date_deadline = deadline

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('sprint_id') or vals.get('date_deadline'):
                continue
            deadline = self._deadline_for_week(
                self.env['qa_testapp.sprint'].browse(vals['sprint_id']))
            if deadline:
                vals['date_deadline'] = deadline
        tasks = super().create(vals_list)
        tasks._ensure_deadline_weeks()
        tasks._sync_week_from_deadline()
        return tasks

    def write(self, vals):
        """Moving a task to another week re-dates it to that week.

        This is what makes the Kanban drag and drop work: the board writes
        nothing but ``sprint_id``, and the deadline follows on its own — the
        Sunday that closes the target week.

        An explicit ``date_deadline`` in the same write wins. That is the case
        where somebody is deliberately setting both (a form save, an import),
        and silently overwriting what they typed would be worse than leaving
        the pair inconsistent for one record.
        """
        if (vals.get('sprint_id') and 'date_deadline' not in vals
                and not self.env.context.get('ft_skip_week_sync')):
            deadline = self._deadline_for_week(
                self.env['qa_testapp.sprint'].browse(vals['sprint_id']))
            if deadline:
                vals = dict(vals, date_deadline=deadline)
        res = super().write(vals)
        if 'date_deadline' in vals or 'project_id' in vals:
            self._ensure_deadline_weeks()
            self._sync_week_from_deadline()
        return res

    def _sync_week_from_deadline(self):
        """Point each task at the week its deadline falls in.

        The two boards define a week differently and both are right for what
        they do: the one in the Tasks tab groups by the DEADLINE, because that
        is the definition the week summaries are specified against; the
        full-screen Kanban groups by ``sprint_id``, because a Kanban can only
        group by a stored column. Leaving the link empty made the second one
        useless — every task in the project piled into None while the first
        showed them spread across their weeks.

        Keeping the link in step with the deadline is what makes the two agree.
        It also fills in the Week field on the task form, which was blank on
        everything nobody had dragged.

        The context flag is what stops this chasing its own tail: writing
        sprint_id normally moves the deadline to that week's Sunday, which
        would overwrite the very deadline this is following.
        """
        if self.env.context.get('ft_skip_week_sync'):
            return
        Week = self.env['qa_testapp.sprint']
        # Grouped by Monday so a bulk write costs one search per distinct week
        # rather than one per task.
        wanted = {}
        for task in self:
            if not (task.project_id and task.date_deadline):
                continue
            monday = monday_of(task._ft_local_date(task.date_deadline))
            wanted.setdefault(monday, self.browse())
            wanted[monday] |= task
        for monday, tasks in wanted.items():
            week = Week.search([('start_date', '=', monday)], limit=1)
            stale = tasks.filtered(lambda task: task.sprint_id != week)
            if week and stale:
                stale.with_context(ft_skip_week_sync=True).write(
                    {'sprint_id': week.id})

    def _ensure_deadline_weeks(self):
        """Make sure every week these tasks are due in exists.

        This is what keeps the boards populated without anybody creating a
        week: scheduling a task IS creating its week. Called on create and
        whenever a deadline or a project changes, which is every way a task can
        arrive in a week it was not in before.

        Collected into one set of days, so a write over a hundred tasks costs
        a single search and a single create rather than one of each per task.
        """
        days = {
            task._ft_local_date(task.date_deadline)
            for task in self if task.project_id and task.date_deadline
        }
        self.env['qa_testapp.sprint']._ensure_weeks(days)
