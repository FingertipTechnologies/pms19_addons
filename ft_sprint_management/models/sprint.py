from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import format_datetime

from .week_utils import (
    WEEK_LENGTH, local_day_bounds, monday_of, sunday_of, week_label,
)

# The PMS task workflow, keyed by the lower-cased STAGE NAME. Stage records
# carry no technical marker for "this is the Testing column", and
# bt_project_customization already keys its own stage rules (Planned -> Working
# -> Testing -> Completed) off the same names, so the summary reads them the
# same way rather than inventing a second, conflicting source of truth.
WEEK_STAGES = ('planned', 'working', 'testing', 'completed')


class ProjectWeek(models.Model):
    """A Monday-to-Sunday week, shared by every project.

    There is exactly one week record per Monday. A week is a position in the
    calendar, not a thing a project owns, so it is not cut into one copy per
    project: the seven days of W41 are the same seven days whichever project is
    looking at them, and a row per project only meant the same week appearing
    four times in the list with the work split between the copies.

    A week therefore reports on every project at once, and the project is a
    property of the tasks inside it — picked per task in Assigned Tasks, and
    printed on every card of the board.

    The model and its column names are deliberately left as they were: the
    database already carries ``qa_testapp_sprint`` and ``project_task.sprint_id``
    and renaming them buys nothing that the labels do not. Everything a user
    sees — menus, views, fields, filters — says "Week".
    """
    _name = 'qa_testapp.sprint'
    _description = 'Project Week'
    # Ascending, so Week 1 / Week 2 / Week 3 read left to right in the Kanban
    # columns and top to bottom in the list.
    _order = 'start_date, id'

    name = fields.Char(
        string='Week Name', compute='_compute_name', store=True,
        help='Continuous week number, counted from the first week of 2026. '
             'The count runs on through the turn of the year, so the last week '
             'of 2026 is W53 and the first of 2027 is W54.',
    )
    start_date = fields.Date(
        string='Start Date',
        default=lambda self: monday_of(fields.Date.context_today(self)),
        required=True,
        help='Monday that opens the week. A date falling mid-week is moved '
             'back to its Monday.',
    )
    end_date = fields.Date(
        string='End Date',
        compute='_compute_end_date', store=True,
        help='Sunday that closes the week. Always Start Date + 6 days.',
    )

    is_current_week = fields.Boolean(
        string='Current Week', compute='_compute_is_current_week',
        help='True for the week today falls in. The Weeks list opens on it.',
    )

    # Read by Kanban grouping (Odoo's _fold_name is 'fold'), not shown anywhere.
    #
    # The server opens only the first ten columns of a grouped Kanban
    # (web.models.MAX_NUMBER_OPENED_GROUPS) and sends the rest folded. The
    # Week Board runs its weeks oldest first, so on any project with more than
    # ten weeks behind it the first ten were history and the week being worked
    # arrived folded - scrolled to, but as a closed strip. A folded group does
    # not count towards the ten, so folding the weeks BEFORE the current one
    # leaves the ten open columns to this week and the ones coming up. The past
    # stays one click away, unfolded by its header.
    #
    # Only on the Week Board: it keys off the ft_current_week_id the board's
    # action puts in the context, so the Weeks list, All Tasks grouped by week
    # and every other view read False and fold nothing.
    fold = fields.Boolean(
        string='Folded in Week Board', compute='_compute_fold',
        help='Technical: folds the weeks before the current one on the Week '
             'Board, so the current week opens unfolded.',
    )

    board_project_id = fields.Many2one(
        'project.project', string='Project',
        compute='_compute_board_project_id', readonly=False, store=False,
        help='Show one project only. Leave empty to see every project, which '
             'is how the week opens.',
    )

    # The tasks explicitly assigned to this week. This is what the Week Kanban
    # drags between columns; the summary below counts by deadline instead.
    task_ids = fields.One2many('project.task', 'sprint_id', string='Assigned Tasks')

    # Everything below reports on the tasks whose DEADLINE falls inside the
    # week, which is the definition the summary screen is specified against. A
    # task assigned to the week always qualifies — assigning it sets its
    # deadline to the week's Sunday — but a task whose deadline was set by hand
    # is counted here too, without anyone having to link it up first.
    week_task_ids = fields.Many2many(
        'project.task', string='Tasks',
        compute='_compute_week_summary',
        help='Every task, in any project, whose deadline falls inside the week.',
    )
    # What the Assigned Tasks tab lists: exactly the cards on the Tasks tab,
    # narrowed by the Project selector the same way. It used to be task_ids,
    # which is every task whose sprint_id points here — including tasks whose
    # deadline has since moved out of the week and so are on no board of it.
    # A separate field rather than week_task_ids a second time in the view:
    # that one is read-only, and these rows stay editable. The edits reach the
    # tasks through the x2many's own update commands, so the inverse has
    # nothing left to do.
    assigned_task_ids = fields.Many2many(
        'project.task', string='Assigned Tasks',
        compute='_compute_assigned_task_ids', inverse='_inverse_assigned_task_ids',
        readonly=False,
        help='The tasks shown on the Tasks tab, for the selected project.',
    )
    task_count = fields.Integer(string='Total Tasks', compute='_compute_week_summary')
    # Where the selected project's week stands, read off its tasks. The week
    # used to carry a Status of its own and lost it in 19.0.3.4.0, rightly: an
    # All Projects week spans projects at four different stages and none of
    # them was ever true of the row. Narrowed to ONE project the question has
    # an answer again, and this is it — computed, because the project is a
    # filter that is not stored, so there is no row a typed status could live
    # on. Empty for All Projects, where the form hides it; Planned for a
    # project with nothing due that week.
    board_status = fields.Selection(
        [(name, name.capitalize()) for name in WEEK_STAGES],
        string='Week Status', compute='_compute_week_summary',
        help="How far the selected project's work for this week has got: the "
             "earliest stage any of its tasks is still in. Planned until "
             "every task has at least started, Completed only when every task "
             "is, and Planned when the project has nothing due this week. "
             "Shown only when a project is selected.",
    )
    planned_task_count = fields.Integer(string='Planned Tasks', compute='_compute_week_summary')
    working_task_count = fields.Integer(string='Working Tasks', compute='_compute_week_summary')
    testing_task_count = fields.Integer(string='Testing Tasks', compute='_compute_week_summary')
    completed_task_count = fields.Integer(string='Completed Tasks', compute='_compute_week_summary')

    total_estimated_hours = fields.Float(
        string='Total Estimated Hours', compute='_compute_week_summary',
        help='Estimated hours of every task due in this week.',
    )
    open_estimated_hours = fields.Float(
        string='Open Estimated Hours', compute='_compute_week_summary',
        help='Estimated hours still to deliver: the total less what is already '
             'in the Completed stage.',
    )
    completed_estimated_hours = fields.Float(
        string='Completed Estimated Hours', compute='_compute_week_summary',
        help='Estimated hours of the tasks in the Completed stage.',
    )
    completed_actual_hours = fields.Float(
        string='Completed Actual Hours', compute='_compute_week_summary',
        help='Hours actually logged against the tasks in the Completed stage.',
    )

    # --------------------------------------------------------------------
    # Computes
    # --------------------------------------------------------------------
    @api.depends('start_date')
    @api.depends_context('ft_week_board_project_id')
    def _compute_board_project_id(self):
        """A view filter, not a property of the week.

        The week itself belongs to no project — there is one record per Monday
        and it holds every project's work. This is the control that narrows
        what is being LOOKED at: pick a project and the summary and the board
        below both come down to it; leave it empty and the week reports on
        everything, which is how it opens.

        Not stored, so it is nobody else's filter and the Weeks list never
        shows whatever the last person left it on.

        Kept for as long as the week stays open, though. The board widget
        puts the chosen project in the form's own context under
        ``ft_week_board_project_id``, and every reload that form makes — the
        one after a drag and drop above all — sends it back and gets the same
        project here. Before, those reloads computed it empty and the board
        jumped to All Projects in the middle of the work. Leaving the week and
        coming back opens a fresh form without the key, so it starts at All
        Projects again.

        Searched rather than browsed, so a project the user cannot read falls
        back to All Projects instead of failing the read.
        """
        project = self.env['project.project']
        project_id = self.env.context.get('ft_week_board_project_id')
        if project_id:
            project = project.search([('id', '=', project_id)], limit=1)
        for week in self:
            week.board_project_id = project

    @api.depends('start_date')
    @api.depends_context('ft_current_week_id')
    def _compute_fold(self):
        current_id = self.env.context.get('ft_current_week_id')
        current_start = current_id and self.browse(current_id).exists().start_date
        for week in self:
            week.fold = bool(
                current_start and week.start_date and week.start_date < current_start
            )

    @api.depends('start_date', 'end_date')
    @api.depends_context('tz')
    def _compute_is_current_week(self):
        """Is today inside this week?

        Computed rather than derived in the view. A list decoration is
        evaluated against the record's own field values and has no notion of
        today, and a stored flag would be true until midnight on the following
        Sunday and then wrong for everyone until something recomputed it — a
        cron nobody would remember to add. Read afresh on every read, so the
        answer is right whenever the list is opened.

        Today is the reader's, from their timezone, exactly as deadlines are
        placed in weeks (see _tasks_by_week). depends_context on tz so two
        users in different timezones do not share one cached answer across the
        hours where their calendars disagree.
        """
        today = fields.Date.context_today(self)
        for week in self:
            week.is_current_week = bool(
                week.start_date and week.end_date
                and week.start_date <= today <= week.end_date
            )

    @api.depends('start_date')
    def _compute_name(self):
        """Name the week by its continuous number: W1 in January 2026, on up.

        Counted from a fixed Monday (week_utils.WEEK_EPOCH, the first week of
        2026) rather than restarted every January, so the number never repeats
        and the year does not have to be carried beside it to tell two weeks
        apart: the last week of 2026 is W53 and the first of 2027 is W54.

        Weeks from before 2026 keep their ISO name, year and all — see
        week_label for why.

        Computed, not typed. A week is not a thing somebody names; it is a
        position in the calendar, and its number follows from its Monday. It
        also has to be derived for the weeks this module creates on its own,
        which no one is present to name.

        Worth knowing: this is deliberately NOT Odoo's own week format ("'W'w
        YYYY" in odoo/orm/models.py). The stock All Tasks board grouped by
        deadline week still labels its columns W1 2027 where this module says
        W54 — the same seven days under two names.
        """
        for week in self:
            week.name = week_label(week.start_date) if week.start_date else False

    @api.depends('start_date')
    def _compute_end_date(self):
        for week in self:
            week.end_date = sunday_of(week.start_date) if week.start_date else False

    @api.depends('start_date', 'end_date', 'board_project_id')
    def _compute_week_summary(self):
        """Count and total the tasks due inside the week.

        Not stored: every figure here reads other records (their stage, their
        estimate, their timesheets), so a stored value would go stale the
        moment a task moves and would need a dependency on half of
        project.task to stay honest. Recomputing on read keeps the summary
        current — reopening or reloading the week always shows today's truth.

        Narrowed by board_project_id where the reader has set one, so the
        figures always describe what is on the board beneath them. It computes
        empty everywhere but the open form, so the Weeks list keeps counting
        every project.
        """
        Task = self.env['project.task']
        tasks_by_week = self._tasks_by_week()
        for week in self:
            tasks = tasks_by_week.get(week.id, Task.browse())
            if week.board_project_id:
                tasks = tasks.filtered(
                    lambda task: task.project_id == week.board_project_id)
            by_stage = {name: Task.browse() for name in WEEK_STAGES}
            for task in tasks:
                stage = (task.stage_id.name or '').strip().lower()
                if stage in by_stage:
                    by_stage[stage] |= task
            completed = by_stage['completed']

            week.week_task_ids = tasks
            week.task_count = len(tasks)
            # Shown whenever a project is selected. A project with nothing due
            # this week has not started anything in it, so it reads Planned —
            # _board_status itself would call an empty set Completed.
            if not week.board_project_id:
                week.board_status = False
            elif not tasks:
                week.board_status = 'planned'
            else:
                week.board_status = self._board_status(tasks, by_stage)
            week.planned_task_count = len(by_stage['planned'])
            week.working_task_count = len(by_stage['working'])
            week.testing_task_count = len(by_stage['testing'])
            week.completed_task_count = len(completed)

            total_estimated = sum(tasks.mapped('estimated'))
            completed_estimated = sum(completed.mapped('estimated'))
            week.total_estimated_hours = total_estimated
            week.completed_estimated_hours = completed_estimated
            week.open_estimated_hours = total_estimated - completed_estimated
            week.completed_actual_hours = sum(completed.mapped('effective_hours'))

    @api.depends('start_date', 'end_date', 'board_project_id')
    def _compute_assigned_task_ids(self):
        # week_task_ids is already the Tasks tab's set, project filter applied.
        for week in self:
            week.assigned_task_ids = week.week_task_ids

    def _inverse_assigned_task_ids(self):
        # Membership follows from each task's deadline and project, so there is
        # no link to write; edited rows were saved by their update commands.
        pass

    @staticmethod
    def _board_status(tasks, by_stage):
        """The stage a set of tasks has reached AS A WHOLE.

        The earliest stage any task is still in, not the furthest any has
        got: a week with one task in Testing and four not yet started is not a
        testing week, it is a planned one with a head start. So Completed only
        when every task is, and otherwise the first of Planned, Working,
        Testing that still holds a task.

        A task in a stage outside the four — "New", "Analysis", anything a
        project added to its own kanban — has not been placed in the workflow
        at all, so it counts as not started and holds the status at Planned;
        by_stage does not contain it, which is what the first test catches.
        """
        if len(by_stage['completed']) == len(tasks):
            return 'completed'
        unplaced = tasks - sum(by_stage.values(), tasks.browse())
        if by_stage['planned'] or unplaced:
            return 'planned'
        if by_stage['working']:
            return 'working'
        return 'testing'

    @api.model
    def _ensure_weeks(self, days):
        """Get, or create, the weeks containing ``days``.

        Weeks are not something anybody should have to sit down and create.
        They are the calendar; the only question is which of them the company
        has work in, and the task deadlines already answer that. So a week
        materialises the moment a task is due in it, which is why the boards
        can show their columns without anyone having prepared them.

        Only the weeks that are actually used. Provisioning a whole year up
        front would put fifty-two columns on a board to carry a handful of
        tasks — the All Tasks board grouped by deadline week does the same
        thing, which is why its columns skip from W41 to W43.

        One week per Monday for the whole database, whichever project the
        deadline belonged to.

        Idempotent: it searches before it creates, so it can be called on every
        board read and on every deadline write without piling up duplicates.
        """
        weeks = self.browse()
        mondays = {monday_of(day) for day in days if day}
        if not mondays:
            return weeks
        existing = self.search([('start_date', 'in', list(mondays))])
        missing = mondays - set(existing.mapped('start_date'))
        created = self.browse()
        if missing:
            # sudo: a week appears as a side effect of somebody scheduling a
            # task or opening a board, and whoever does that is not
            # necessarily provisioning calendar records on purpose.
            created = self.sudo().create([
                {'start_date': monday} for monday in sorted(missing)
            ]).with_env(self.env)
        return existing | created

    def _tasks_by_week(self, tasks=None):
        """The tasks due in each of these weeks, keyed by week id.

        ONE query for the whole recordset, not one per week. The week list
        shows eighty rows at a time and every column on it is part of this
        summary, so a search per record turned opening the list into eighty
        round trips against project_task. The whole span is read once and the
        tasks are bucketed by the local calendar day their deadline falls on.

        ``tasks`` is the set to bucket, for a caller that is already holding
        one. The project's week board is: its tasks are that project's own and
        deliberately complete — delivered and archived work included, see
        project.project._ft_tasks_by_project. Left to search for itself this
        read the whole COMPANY's span and the board then intersected the answer
        back down to the project, which cost a second query over far more rows
        and, worse, quietly lost whatever that search could not return. An
        archived task never came back from it, so it was in the board's task
        set but in none of its weeks, and fell through to the "No Week" column
        with the tasks that have no deadline at all.

        Without it, nothing changes: the week's own summary and the board on
        the Week form still ask for every project's work in the span, which is
        what a week reports on.
        """
        Task = self.env['project.task']
        result = {}
        weeks = self.filtered(lambda week: week.start_date and week.end_date)
        if not weeks:
            return result
        if tasks is None:
            tasks = Task.search(self._project_domain() + [
                ('date_deadline', '>=', local_day_bounds(
                    self.env, min(weeks.mapped('start_date')))),
                ('date_deadline', '<=', local_day_bounds(
                    self.env, max(weeks.mapped('end_date')), end_of_day=True)),
            ])
        by_day = {}
        for task in tasks:
            # Only a set handed in can hold these: the search above is bounded
            # by the deadline, so it cannot return a task without one.
            if not task.date_deadline:
                continue
            # In the reader's timezone, not UTC: a deadline of 23:00 IST is
            # already the next day in UTC and would land in the wrong week —
            # the one the user can see it is not in.
            day = fields.Datetime.context_timestamp(
                task, task.date_deadline).date()
            by_day.setdefault(day, []).append(task.id)
        for week in weeks:
            ids = []
            for offset in range(WEEK_LENGTH):
                ids += by_day.get(week.start_date + timedelta(days=offset), [])
            result[week.id] = Task.browse(ids)
        return result

    # --------------------------------------------------------------------
    # Onchanges & constraints
    # --------------------------------------------------------------------
    @api.onchange('start_date')
    def _onchange_start_date(self):
        # Snap in the form as well as on save, so the user sees the Monday and
        # the Sunday that will actually be stored before they save.
        if self.start_date:
            self.start_date = monday_of(self.start_date)

    @api.constrains('start_date')
    def _check_no_duplicate_week(self):
        """One week per Monday, for the whole database.

        Start dates are snapped to Monday, so two weeks sharing a start date
        cover exactly the same days — and every task due in them would be
        counted, and its hours totalled, twice. It is also the duplicate
        hardest to spot, because both rows read "W41" and report the same
        figures.

        Enforced in Python rather than as a SQL constraint on purpose: a unique
        index has to be built over the existing rows at upgrade time, and any
        duplicate already in the database would fail the upgrade instead of
        being fixed at leisure.
        """
        for week in self:
            if not week.start_date:
                continue
            clash = self.search_count([
                ('id', '!=', week.id),
                ('start_date', '=', week.start_date),
            ])
            if clash:
                raise ValidationError(_(
                    "There is already a week starting on %(date)s.\n\n"
                    "Weeks run Monday to Sunday and may not overlap, or every "
                    "task due that week would be counted twice.",
                    date=week.start_date,
                ))

    # --------------------------------------------------------------------
    # CRUD
    # --------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._snap_start_date(vals)
        return super().create(vals_list)

    def write(self, vals):
        self._snap_start_date(vals)
        return super().write(vals)

    @api.model
    def _snap_start_date(self, vals):
        """Move a mid-week start date back to its Monday.

        Done in create/write and not only in the onchange, because imports, the
        ORM and any automated caller never fire onchanges — and a week that did
        not start on a Monday would silently break the Monday/Sunday rule the
        whole module rests on.
        """
        if vals.get('start_date'):
            vals['start_date'] = monday_of(fields.Date.to_date(vals['start_date']))

    # --------------------------------------------------------------------
    # Helpers & actions
    # --------------------------------------------------------------------
    def _week_task_domain(self):
        """Every task whose deadline falls inside the week."""
        self.ensure_one()
        if not (self.start_date and self.end_date):
            return [('id', '=', False)]
        return self._project_domain() + [
            ('date_deadline', '>=', local_day_bounds(self.env, self.start_date)),
            ('date_deadline', '<=', local_day_bounds(self.env, self.end_date, end_of_day=True)),
        ]

    @api.model
    def _project_domain(self):
        """The project half of a week's task domain.

        A week covers every project, so there is nothing to narrow to — only
        `project_id != False`, which keeps private to-dos out. A private task
        belongs to a person, not to a project, and nothing on these boards
        reports on it.
        """
        return [('project_id', '!=', False)]

    def get_board_data(self, project_id=False, expanded_column_ids=None):
        """The week's tasks as stage columns, for the board in the Tasks tab.

        Shaped here rather than in the widget. An embedded x2many cannot be
        grouped by Odoo — the StaticList behind it has no grouping at all — so
        the board is drawn by hand, and doing the grouping, ordering and
        formatting in Python leaves the JavaScript a renderer with no business
        rules of its own.

        ``field`` tells the widget what a drop writes. The same widget draws
        the project's week board, which writes sprint_id instead, so the field
        travels with the data rather than being configured twice.

        ``project_id`` is the Project filter above the board, passed in by the
        widget rather than read off the record: it is not stored, so a record
        read on the server would only ever compute it empty.

        ``expanded_column_ids`` are the columns whose "+ N more" has been
        clicked, drawn without the per-column card cap. The widget remembers
        them across reloads of the same record, so a drag and drop does not
        fold a column somebody had just opened out.
        """
        self.ensure_one()
        # The tasks straight from _tasks_by_week, not through week_task_ids:
        # that field is one of a dozen filled by _compute_week_summary, so
        # reading it here ran the whole summary — stage counts, hour totals,
        # the logged hours of every completed task — for a board that uses
        # none of it, and that on every page of the pager.
        tasks = self._tasks_by_week().get(self.id, self.env['project.task'])
        if project_id:
            tasks = tasks.filtered(lambda task: task.project_id.id == project_id)
        return {
            'field': 'stage_id',
            # The columns are the stages here, so a stage on each card would
            # only repeat the heading above it.
            'show_stage': False,
            # The project, though, is exactly what a reader cannot tell the
            # cards apart without: the week holds every project's work. Unless
            # it has been filtered down to one, when every card would carry the
            # same name.
            'show_project': not project_id,
            'columns': self._board_stage_columns(
                tasks, set(expanded_column_ids or ())),
        }

    def _board_stage_columns(self, tasks, expanded_column_ids=()):
        """One column per stage NAME, not per stage record.

        A ``project.task.type`` is not global. It is linked to projects through
        ``project_task_type_rel``, so "Planned" is not one row shared by the
        whole database — it is one row per set of projects that happen to share
        a stage list. Three sources create them (see the module README), and
        between them a PMS ends up with several distinct rows all called
        Planned.

        A week spans every project, so searching those names returned every one
        of those rows and drew a column for each: two Planned headings, the
        second usually empty because its projects had nothing due that week.
        Grouping by name collapses them back into the four columns people
        expect, and the tasks of every same-named stage land in one place.

        A stage whose name is not one of the four still gets a column, at the
        end. Dropping it would take the cards sitting in it off the board with
        no way to drag them back, which is worse than an extra heading — the
        heading at least says out loud that the stage set needs cleaning up.
        """
        Stage = self.env['project.task.type']
        canonical = [name.capitalize() for name in WEEK_STAGES]
        # Personal stages (user_id set) are My Tasks' own kanban columns and
        # belong to a person, not to the delivery workflow. They would appear
        # as a second "In Progress" or a stray name nobody recognises.
        stages = Stage.search([
            ('name', 'in', canonical), ('user_id', '=', False),
        ]) | tasks.stage_id

        groups = {}
        for stage in stages.sorted(lambda stage: (stage.sequence, stage.id)):
            groups[stage.name] = groups.get(stage.name, Stage.browse()) | stage

        def order(name):
            # The four in workflow order first, everything else after, so a
            # stray stage cannot push Completed off to the right.
            if name in canonical:
                return (0, canonical.index(name))
            return (1, groups[name][:1].sequence)

        final_stage_ids = set(tasks._ft_final_stage_ids())
        columns = []
        for name in sorted(groups, key=order):
            group = groups[name]
            # A merged column writes the FIRST of its stages on a drop. After
            # the 19.0.4.3.0 migration each name is a single row and there is
            # nothing to choose between; before it, the lowest sequence is the
            # one the four canonical records carry.
            columns.append(
                tasks.filtered(lambda task, g=group: task.stage_id in g)
                ._board_column(
                    group[0].id, name,
                    expanded=group[0].id in expanded_column_ids,
                    final_stage_ids=final_stage_ids)
            )
        return columns

    def action_view_tasks(self):
        """Open the week's tasks as a Kanban grouped by stage.

        Carries the Project filter through, so the button opens the same set of
        tasks the count on it was taken from.
        """
        self.ensure_one()
        domain = self._week_task_domain()
        if self.board_project_id:
            domain += [('project_id', '=', self.board_project_id.id)]
        return {
            'type': 'ir.actions.act_window',
            'name': _('%s Tasks') % self.name,
            'res_model': 'project.task',
            'view_mode': 'kanban,list,form',
            'domain': domain,
            'context': {
                'default_sprint_id': self.id,
                # Core expands the stage columns only when this is set, so
                # without it an empty Testing column simply would not be drawn
                # and there would be nowhere to drop a task.
                'project_kanban': True,
            },
        }
