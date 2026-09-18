from datetime import timedelta

from odoo import Command, _, api, fields, models

from .week_utils import monday_of

# Weeks after the current one that are always a column on the project's week
# boards, whether or not anything is due in them yet.
UPCOMING_WEEKS = 4

# The only task stages a project runs on. See data/task_stages.xml.
PMS_TASK_STAGE_XMLIDS = (
    'ft_sprint_management.task_stage_planned',
    'ft_sprint_management.task_stage_working',
    'ft_sprint_management.task_stage_testing',
    'ft_sprint_management.task_stage_completed',
)


class ProjectProject(models.Model):
    _inherit = 'project.project'

    week_ids = fields.Many2many(
        'qa_testapp.sprint', string='Weeks', compute='_compute_week_ids',
        help='The weeks this project has work due in.',
    )
    week_count = fields.Integer(string='Week Count', compute='_compute_week_ids')

    def _ft_pms_task_stages(self):
        stages = self.env['project.task.type']
        for xmlid in PMS_TASK_STAGE_XMLIDS:
            stages |= self.env.ref(xmlid, raise_if_not_found=False) or stages.browse()
        return stages

    @api.model
    def default_get(self, field_names):
        """A new project gets the four PMS task stages and nothing else.

        project_task_default_stage (OCA) defaults type_ids to every stage
        flagged case_default, which is how each project used to arrive with
        Analysis, Specification, Design and the rest beside the four. A stage
        list passed explicitly as default_type_ids still wins.
        """
        defaults = super().default_get(field_names)
        if 'type_ids' in field_names and 'default_type_ids' not in self.env.context:
            stages = self._ft_pms_task_stages()
            if stages:
                defaults['type_ids'] = [Command.set(stages.ids)]
        return defaults

    @api.model
    def name_create(self, name):
        """Core gives a project created on the fly a stage of its own, "New".
        Put the four in its place and drop the stage nothing else uses."""
        res = super().name_create(name)
        stages = self._ft_pms_task_stages()
        if res and stages:
            project = self.browse(res[0])
            extra = project.type_ids - stages
            project.type_ids = [Command.set(stages.ids)]
            unused = extra.filtered(lambda stage: not stage.project_ids)
            if unused and not self.env['project.task'].with_context(
                    active_test=False).search_count(
                        [('stage_id', 'in', unused.ids)], limit=1):
                unused.sudo().unlink()
        return res

    def _ft_tasks_by_project(self):
        """EVERY task of each of these projects, keyed by project id.

        Not ``task_ids``, which is short on both counts a week board cares
        about:

        * Core gives that one2many the domain ``[('is_closed', '=', False)]``,
          and bt_project_customization stamps ``state = '1_done'`` on any task
          that reaches a final stage. So the field leaves out precisely the
          work that is already delivered — and the weeks behind us are exactly
          the weeks whose work is done. They came back holding nothing, the tab
          read "No tasks" across every week that was over, and because
          _compute_week_ids reads the same field those weeks got no column at
          all: the board began at the oldest week with something still OPEN in
          it and the project's history was simply not on it. A card dragged
          into Completed disappeared on the spot for the same reason.

        * It is read with ``active_test: False`` — not a choice project made,
          but what ``One2many.read`` does for every one2many in the ORM (see
          odoo/orm/fields_relational.py). Archived tasks were therefore ON the
          board already, and a plain search here would have quietly taken them
          off it. So the context is set explicitly rather than left to a
          default: it is the behaviour the tab has always had, and "every task"
          is what the board is for.

        The delivered cards are not loud about it — ``_board_cards`` fades
        anything in a final stage, the way a stock Kanban fades a closed
        record.

        One search for the whole recordset rather than one per record: a
        project's task set is read for the Weeks stat button, for the board in
        the Tasks tab and for the full-screen board's columns.
        """
        Task = self.env['project.task'].with_context(active_test=False)
        ids_by_project = {}
        # _origin drops the records that have never been written — the project
        # being typed into a New form, whose stat button is computed like any
        # other. A NewId cannot go into a domain, and there are no task rows
        # pointing at it to find anyway.
        saved = self._origin
        if saved:
            for task in Task.search([('project_id', 'in', saved.ids)]):
                ids_by_project.setdefault(task.project_id.id, []).append(task.id)
        return {
            project.id: Task.browse(ids_by_project.get(project._origin.id, []))
            for project in self
        }

    def _ft_tasks(self):
        """Every task of this one project. @see _ft_tasks_by_project."""
        self.ensure_one()
        return self._ft_tasks_by_project()[self.id]

    # task_ids is still the dependency: it is the only x2many the ORM can
    # watch, and it covers every open task. A closed task's deadline moving
    # without anything else changing in the same transaction is the one case it
    # misses, and the field is not stored — the next request reads it afresh.
    @api.depends('task_ids.date_deadline')
    def _compute_week_ids(self):
        """The weeks this project has work in.

        Read, not owned. A week is one record for the whole database — the
        seven days of W41 are the same seven days for every project — so a
        project cannot hold a one2many of its own weeks any more. What it does
        have is a span: the weeks its task deadlines land in, which is exactly
        what the Weeks button counts and what the Week Board lays out as
        columns.

        Counted over every task, finished ones included (_ft_tasks_by_project).
        A week whose work is all delivered is still a week this project had
        work in, and leaving it out took the whole of the project's history off
        both boards.
        """
        Week = self.env['qa_testapp.sprint']
        tasks_by_project = self._ft_tasks_by_project()
        for project in self:
            mondays = {
                monday_of(task._ft_local_date(task.date_deadline))
                for task in tasks_by_project[project.id] if task.date_deadline
            }
            weeks = Week.search(
                [('start_date', 'in', list(mondays))]) if mondays else Week.browse()
            project.week_ids = weeks
            project.week_count = len(weeks)

    def get_board_data(self, expanded_column_ids=None):
        """The project's tasks as week columns, for the board in the Tasks tab.

        A task belongs to the week its DEADLINE falls in — the same test the
        Week form's own summary uses, run by the same code
        (qa_testapp.sprint._tasks_by_week), so the two cannot bucket a task
        differently. What they hand it differs, and deliberately: the week
        summarises what a search over every project returns, while this board
        hands it the project's own tasks, which is a wider set than a search —
        archived work included. It is also what "All Tasks grouped by deadline
        week" shows, which is the board people already read.

        The weeks themselves are shared with every other project. This board
        draws the columns for the span this project has work in and fills them
        from its own tasks, so the cards stay this project's even though the
        calendar behind them is the company's.

        Membership is therefore not the Week link. That matters most for the
        backlog: every task raised before this module existed has no link, and
        keying the columns on it left the whole project in one "No Week" heap
        until somebody dragged it out card by card. Keyed on the deadline they
        already have, they land in their week on the first page load.

        Nor is it "still open". The board shows every task the project has,
        delivered ones included, because a week that is over is exactly the
        week whose work is done — read off ``task_ids`` those weeks came back
        empty, and a card dragged into Completed disappeared off the board
        instead of settling at the bottom of its column. See
        _ft_tasks_by_project.

        A drop still writes ``sprint_id`` rather than the deadline directly:
        project.task.write moves the deadline to that week's Sunday in
        response, so one write sets both and the link stays populated for the
        task form and the week's Assigned Tasks tab.

        ``expanded_column_ids`` are the columns whose "+ N more" has been
        clicked, drawn without the per-column card cap; ``false`` in the list
        is the No Week column, which has no record to be identified by.

        Exactly one column comes back flagged ``current`` — the week today
        falls in. The board is a calendar that runs from the project's first
        deadline to four weeks out, so the week being worked is somewhere in
        the middle of it and was never where the tab opened; the flag is what
        lets the widget colour it and scroll to it. Taken from the reader's
        own today, the same way deadlines are placed in weeks.
        """
        self.ensure_one()
        expanded = set(expanded_column_ids or ())
        current_monday = monday_of(fields.Date.context_today(self))
        # Every task in the project — delivered and archived work included,
        # NOT task_ids, which leaves out the first and would have left the
        # board reading "No tasks" across every week that was over. See
        # _ft_tasks_by_project.
        tasks = self._ft_tasks()
        # Legacy data never went through the deadline hook that creates a
        # week, so provision anything still missing before the columns are
        # drawn. Idempotent, and on a project that is already covered it costs
        # one search.
        self._ensure_task_weeks(tasks)
        # Every week across the project's span, work in it or not: a board is
        # where the next weeks get planned, and a week with no column cannot
        # have a task dropped into it.
        weeks = self._ft_board_weeks().sorted('start_date')
        # THESE tasks bucketed by their deadline, not a fresh search of the
        # whole company intersected back down to them. The set above is
        # deliberately wider than any search this side would make, so anything
        # it holds that a search cannot return — an archived task — was in the
        # board's tasks and in none of its weeks, and landed in "No Week".
        by_week = weeks._tasks_by_week(tasks)
        empty = self.env['project.task'].browse()
        scheduled = empty
        final_stage_ids = set(tasks._ft_final_stage_ids())
        columns = []
        for week in weeks:
            in_week = by_week.get(week.id, empty)
            scheduled |= in_week
            columns.append(in_week._board_column(
                week.id, week.display_name, expanded=week.id in expanded,
                current=week.start_date == current_monday,
                final_stage_ids=final_stage_ids))
        # Everything the weeks do not cover: no deadline at all, or one that
        # falls outside every week defined for this project. Not droppable —
        # there is no deadline a drop here could derive, and clearing one is a
        # deliberate act for the task form, not a side effect of a drag.
        unscheduled = (tasks - scheduled)._board_column(
            False, _('No Week'), expanded=False in expanded,
            final_stage_ids=final_stage_ids)
        unscheduled['droppable'] = False
        # Columns are weeks here, so the stage is the one thing a card cannot
        # be read without.
        return {
            'field': 'sprint_id',
            'show_stage': True,
            'show_project': False,
            'columns': [unscheduled] + columns,
        }

    @api.model
    def _ft_planning_weeks(self):
        """The current week and the UPCOMING_WEEKS after it, created if missing.

        The current week is the reader's, from their timezone, the same way
        deadlines are placed in weeks.
        """
        monday = monday_of(fields.Date.context_today(self))
        return self.env['qa_testapp.sprint']._ensure_weeks([
            monday + timedelta(weeks=offset)
            for offset in range(UPCOMING_WEEKS + 1)
        ])

    def _ft_board_weeks(self):
        """Every week the board covers, running continuously with no gaps.

        week_ids is only the weeks a task deadline actually lands in, so a week
        in the middle of a project that happens to hold no work produced no
        column at all and the board read W33, W34, W36 - the numbers skipping
        wherever nobody had anything due. A board is a calendar before it is a
        report: the weeks have to run consecutively for the numbering to mean
        anything, and an empty week is precisely where the next piece of work
        needs dropping.

        So the span is filled rather than collected. It runs from the earliest
        week to the latest of the weeks with work in them and the planning
        weeks, which keeps the current week and the ones coming up on the board
        even for a project whose work is all in the past, and keeps the last
        weeks of work on it for one whose deadlines are all behind us.

        The intermediate weeks are created as they are needed. _ensure_weeks is
        idempotent and deliberately does NOT provision a calendar up front -
        that is what stops every unused week in the year becoming a column -
        so the weeks materialised here are only ever the ones inside a span a
        project already reaches across.
        """
        self.ensure_one()
        weeks = self.week_ids | self._ft_planning_weeks()
        if not weeks:
            return weeks
        starts = weeks.mapped('start_date')
        first, last = min(starts), max(starts)
        return self.env['qa_testapp.sprint']._ensure_weeks([
            first + timedelta(weeks=offset)
            for offset in range((last - first).days // 7 + 1)
        ])

    def _ensure_task_weeks(self, tasks=None):
        """Provision the weeks this project's task deadlines fall in.

        ``tasks`` is the project's tasks where the caller is already holding
        them, so drawing a board costs one search for them rather than two.
        """
        self.ensure_one()
        if tasks is None:
            tasks = self._ft_tasks()
        days = {task._ft_local_date(task.date_deadline)
                for task in tasks if task.date_deadline}
        self.env['qa_testapp.sprint']._ensure_weeks(days)
        self.invalidate_recordset(['week_ids', 'week_count'])

    def action_view_weeks(self):
        self.ensure_one()
        self._ensure_task_weeks()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Weeks'),
            'res_model': 'qa_testapp.sprint',
            'view_mode': 'list,kanban,form',
            # The weeks this project has work in — a slice of the shared
            # calendar, not weeks of its own.
            'domain': [('id', 'in', self.week_ids.ids)],
            'context': {'default_project_id': self.id},
        }

    def action_view_week_board(self):
        """The project's tasks as a Kanban with one column per week.

        A grouped Kanban cannot be embedded in a form: the Tasks tab's
        one2many renders its records as a flat list of cards with no grouping
        and no drag and drop, so the board is opened as a view of its own. That
        is also what gets the behaviour for free — dragging a card writes
        ``sprint_id``, and project.task moves the deadline to the new week's
        Sunday.

        ``default_project_id`` is what tells ``_read_group_sprint_ids`` which
        project's weeks to lay out as columns, so it must stay in the context.

        ``ft_current_week_id`` is the week today falls in. The columns run
        oldest first, the way a calendar reads — left is behind us, right is
        still to come — so on a project with any history the board opened
        somewhere in its past with the week being worked off the right-hand
        edge. The id travels in the context rather than being looked up by the
        client: the action already has a cursor open, and it saves the board a
        round trip before it can draw. ft_week_kanban colours that column and
        scrolls it into view (static/src/week_kanban/week_kanban.js).

        The week is created if it does not exist yet, the same way every other
        week in this module comes into being — so the board always has a column
        to open on, even on a project with nothing due this week.
        """
        self.ensure_one()
        current_week = self.env['qa_testapp.sprint']._ensure_weeks(
            [fields.Date.context_today(self)])
        return {
            'type': 'ir.actions.act_window',
            'name': _('%s — Week Board') % self.name,
            'res_model': 'project.task',
            'view_mode': 'kanban,list,form',
            'views': [
                (self.env.ref('ft_sprint_management.view_task_kanban_week').id, 'kanban'),
                (False, 'list'),
                (False, 'form'),
            ],
            'domain': [('project_id', '=', self.id)],
            'context': {
                'default_project_id': self.id,
                'project_kanban': True,
                'ft_current_week_id': current_week.id,
            },
        }
