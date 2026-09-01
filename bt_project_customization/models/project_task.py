from datetime import datetime, timedelta

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError

# Minimum number of characters required in a task title.
TASK_TITLE_MIN_LEN = 20

# Job positions (hr.job) allowed to create tasks. Matched on the lower-cased
# job name, mirroring the classification used elsewhere in the PMS.
TASK_CREATE_JOBS = {
    'technical lead',
    'project manager',
    'project coordinator',
    'project cordinator',   # legacy typo present in source data
}

# Task stage names that mean the work is delivered even when the Kanban "Folded
# in Kanban" flag was never ticked on the stage.
#
# `fold` is Odoo's own marker for a closed stage and remains the primary test,
# but it cannot be the only one. On the production database every delivery figure
# read zero, because 6,768 active tasks sat across 489 non-folded stages and NOT
# ONE task was in a folded stage — the 200 folded "Done" stages are unused
# per-project defaults. The workflow actually in use is Working / Completed /
# Planned / Testing, of which only Completed is final, and nobody had ticked
# Folded on it.
#
# Matching the name as well makes the metrics correct on a stage set whose fold
# flags were never maintained, while still honouring `fold` wherever it IS set.
# Ticking Folded on a stage therefore remains a supported way to mark it final —
# this is an addition, not a replacement.
COMPLETED_STAGE_NAMES = ('Completed',)

# User Story workflow roles. These are job-position names because that is the
# role source used throughout the PMS (task creation, dashboard role hours and
# timesheet classification). Technical/Testing leads belong to the same working
# role as the people they lead.
DEVELOPER_JOB_NAMES = ('software developer', 'technical lead')
TESTER_JOB_NAMES = ('software tester', 'testing lead')
PROJECT_MANAGER_JOB_NAMES = (
    'project manager',
    'project coordinator',
    'project cordinator',
)
USER_STORY_STAGE_NAMES = ('planned', 'working', 'testing', 'completed')
PLANNED_CREATE_JOB_NAMES = (
    'project manager',
    'technical lead',
    'project coordinator',
    'project cordinator',
)
UNPLANNED_REASON_MIN_LEN = 20


class ProjectTask(models.Model):
    _inherit = 'project.task'

    estimated = fields.Float(string='Estimated')
    actual = fields.Float(string='Actual')
    ft_reopen_count = fields.Integer(
        string='Times Reopened',
        default=0,
        readonly=True,
        copy=False,
        tracking=True,
        help="How many times this task was sent back for rework. For User "
             "Stories this is Testing to Working; other task types retain the "
             "Completed-to-open rule. Drives the Rework Rate. "
             "Counted from the day this feature was installed onwards, so tasks "
             "reopened before then read 0.",
    )
    ft_rework_hours = fields.Float(
        string='Rework Hours',
        compute='_compute_ft_rework_hours',
        store=True,
        readonly=True,
        help="Time logged after this task was sent back for rework. Zero until "
             "the task is reopened at least once; earlier hours stay "
             "first-round work.",
    )
    ft_reopened_date = fields.Datetime(
        string='Re-Opened Date',
        readonly=True,
        copy=False,
        index=True,
        tracking=True,
        help='The most recent date and time this task was sent back for rework.',
    )
    ft_worked_by_id = fields.Many2one(
        'res.users',
        string='Worked By',
        readonly=True,
        copy=False,
        tracking=True,
        help='User who most recently moved the task into Working.',
    )
    ft_work_start_date = fields.Datetime(
        string='Work Start Date',
        readonly=True,
        copy=False,
        tracking=True,
        help='Date and time the task most recently entered Working.',
    )
    ft_work_end_date = fields.Datetime(
        string='Work End Date',
        readonly=True,
        copy=False,
        tracking=True,
        help='Date and time the task most recently entered Completed.',
    )
    ft_completed_by_id = fields.Many2one(
        'res.users',
        string='Completed By',
        readonly=True,
        copy=False,
        tracking=True,
        help='User who most recently moved the task into Completed.',
    )
    ft_completion_date = fields.Datetime(
        string='Completion Date',
        compute='_compute_ft_completion_date',
        store=True,
        index=True,
        readonly=True,
        help="When this task was delivered — the single date every delivery "
             "metric is measured against. Falls back to the last stage change "
             "when Odoo's own date_end is missing, which happens to any task "
             "that entered a stage before that stage was marked Folded (Odoo "
             "clears date_end when the target stage is not folded). Empty while "
             "the task is open.",
    )
    ft_timeline_status = fields.Selection(
        [
            ('on_time', 'On Time'),
            ('overdue', 'Overdue'),
        ],
        string='Timeline Status',
        compute='_compute_ft_timeline_status',
        store=True,
        readonly=True,
        tracking=True,
        help='On Time when completion is on or before the Deadline; Overdue '
             'when completion is after it. Empty until the task is completed.',
    )
    ft_deadline_change_count = fields.Integer(
        string='Number of Deadline Changes',
        default=0,
        readonly=True,
        copy=False,
        tracking=True,
        help='Number of times an already-set Deadline was changed. Setting the '
             'initial Deadline does not count.',
    )
    module_id = fields.Many2one('cus.module',string="Module",required=True)
    ft_allowed_module_ids = fields.Many2many(
        'cus.module',
        string='Allowed Modules',
        compute='_compute_ft_allowed_module_ids',
        help="The modules this task's project offers. Exists so the Module "
             "field can be filtered against it.",
    )
    wc_id = fields.Char(string='Wc Id')
    task_type = fields.Selection([
        ('user_story', 'User Story'),
        ('internal_call', 'Internal Call'),
        ('external_call', 'External Call'),
    ], string='Task Type', default='user_story', required=True)
    task_source = fields.Selection([
        ('planned', 'Planned'),
        ('unplanned', 'Unplanned'),
        ('change_request', 'Change Request'),
    ], string='Task Source',
        compute='_compute_task_source', store=True, readonly=False, copy=True,
        tracking=True,
        help="Whether this work was scoped up front, came up during the build, "
             "or arrived after the client had seen the product. Filled in from "
             "the project's stage when the project is set, and editable "
             "afterwards.")

    # Depends on project_id ONLY — deliberately not on project_id.stage_id.
    #
    # The source records where the project stood WHEN THE WORK ARRIVED, so it is
    # stamped once and then left alone. Depending on the stage as well would
    # rewrite the source of every task in a project the moment that project
    # advanced: a whole discovery backlog would silently turn into Change
    # Requests the day the project reached UAT, which is the exact figure
    # change-request billing is argued from.
    #
    # store=True with readonly=False is what makes that a DEFAULT rather than a
    # verdict: Odoo runs the compute on create and whenever the project changes,
    # and otherwise leaves whatever a user typed in place.
    @api.depends('project_id')
    def _compute_task_source(self):
        for task in self:
            task.task_source = (
                task.project_id._ft_task_source() if task.project_id else False
            )

    @api.depends('project_id', 'project_id.module_ids')
    def _compute_ft_allowed_module_ids(self):
        every_module = None
        for task in self:
            if task.project_id:
                task.ft_allowed_module_ids = task.project_id.module_ids
                continue
            # A task with no project — Odoo's private tasks — has no
            # configuration to filter against, so every module stays on offer.
            # Searched once for the whole batch, not once per record.
            if every_module is None:
                every_module = self.env['cus.module'].search([])
            task.ft_allowed_module_ids = every_module

    @api.onchange('project_id')
    def _onchange_project_id_ft_module(self):
        """Drop a module the newly chosen project does not offer.

        Without this the field keeps the old project's module and simply stops
        showing it in the dropdown, so the form looks filtered while holding a
        value that the filter would have excluded.
        """
        if (self.module_id and self.project_id
                and self.module_id not in self.project_id.module_ids):
            self.module_id = False

    source_ticket_id = fields.Many2one(
        'ft.helpdesk.ticket',
        string='Customer Ticket',
        tracking=True,
        help='Customer-created portal ticket authorising this Change Request.',
    )
    unplanned_reason = fields.Text(
        string='Unplanned Reason',
        tracking=True,
        help='Why this work was not included in the plan (minimum 20 characters).',
    )

    @api.model_create_multi
    def create(self, vals_list):
        # Only a Technical Lead, Project Manager or Project Coordinator may
        # create tasks. Superuser and system administrators bypass the check so
        # data imports, automation and mail-to-task keep working.
        self._check_task_create_permission()
        tasks = super().create(vals_list)
        tasks._check_planned_creation_permission()
        tasks._check_task_source_rules()
        # Run the required-field checks explicitly. @api.constrains alone is not
        # enough on create: Odoo validates only the fields PRESENT in the values,
        # so leaving estimated and date_deadline out entirely skipped both — a
        # task with no estimate at all sailed through while one explicitly set to
        # 0 was refused. Both methods still exempt superuser, so imports and
        # automation are unaffected.
        tasks._check_estimated_required()
        tasks._check_deadline_required()
        # Same reason as the two above: @api.constrains only validates fields
        # PRESENT in the values, so a create that never mentions user_ids would
        # skip this one. It cannot currently produce two assignees without
        # mentioning them, but that is a property of today's callers, not of the
        # rule, and the rule is cheap to state outright.
        tasks._check_user_story_single_assignee()
        return tasks

    def write(self, vals):
        deadline_changed = self.env['project.task']
        if 'date_deadline' in vals:
            new_deadline = (
                fields.Datetime.to_datetime(vals['date_deadline'])
                if vals['date_deadline'] else False
            )
            # Validate before super().write so form edits, imports and combined
            # stage/deadline updates cannot pass through a later sudo path. This
            # includes Administrators: their exemption is only from the 24-hour
            # minimum, never from the basic future-deadline rule. A migration
            # must opt out explicitly instead of inheriting a broad sudo bypass.
            if not self.env.context.get('skip_ft_deadline_validation'):
                if not new_deadline:
                    raise ValidationError(_("Deadline is required."))
                if new_deadline <= fields.Datetime.now():
                    raise ValidationError(_(
                        "Deadline must be a future date and time.\n\n"
                        "Select a Deadline later than the current date and time."
                    ))
            deadline_changed = self.filtered(
                lambda task: bool(task.date_deadline)
                and task.date_deadline != new_deadline
            )

        if 'stage_id' in vals:
            self._check_planned_stage_write(vals['stage_id'])
            self._check_user_story_stage_move(vals['stage_id'])

        # Count reopens: a task leaving a delivered stage for an open one is
        # rework. Snapshot which records were in a final stage BEFORE the super()
        # call, because stage_id is what we are about to change.
        #
        # Uses the same _ft_final_stage_ids test as the delivery metrics rather
        # than raw `fold`, or a task moved out of Completed would not be counted
        # as reopened on a stage set whose fold flag is unticked — which is every
        # stage set in this database.
        if 'stage_id' not in vals:
            res = super().write(vals)
            self._ft_validate_written(vals)
            for task in deadline_changed:
                task.sudo().write({
                    'ft_deadline_change_count':
                        task.ft_deadline_change_count + 1,
                })
            return res
        final_ids = set(self._ft_final_stage_ids())
        was_final = {t.id: t.stage_id.id in final_ids for t in self}
        was_working = {
            t.id: (t.stage_id.name or '').strip().lower() == 'working'
            for t in self
        }
        was_testing = {
            t.id: (t.task_type == 'user_story'
                   and (t.stage_id.name or '').strip().lower() == 'testing')
            for t in self
        }
        res = super().write(vals)
        for task in deadline_changed:
            task.sudo().write({
                'ft_deadline_change_count': task.ft_deadline_change_count + 1,
            })
        now = fields.Datetime.now()
        moved_to_working = self.filtered(
            lambda t: (not was_working.get(t.id)
                       and (t.stage_id.name or '').strip().lower() == 'working')
        )
        completed = self.filtered(
            lambda t: (not was_final.get(t.id)
                       and t.stage_id.id in final_ids
                       and t.state != '1_canceled')
        )
        reopened = self.filtered(
            lambda t: (
                # User Story rework starts as soon as QA rejects Testing back
                # to Working; it no longer needs an incorrect first completion.
                (was_testing.get(t.id)
                 and (t.stage_id.name or '').strip().lower() == 'working')
                # Preserve the existing Completed -> open behaviour for every
                # other task type.
                or (t.task_type != 'user_story'
                    and was_final.get(t.id)
                    and t.stage_id.id not in final_ids)
            )
        )
        # A return to Working starts a fresh execution/rework cycle. sudo is
        # limited to these readonly audit fields; the actor remains env.user.
        if moved_to_working:
            moved_to_working.sudo().write({
                'ft_worked_by_id': self.env.user.id,
                'ft_work_start_date': now,
                'ft_work_end_date': False,
                'ft_completed_by_id': False,
            })
        # date_end is Odoo's standard Completed Date. Core only stamps it for
        # folded stages, while this PMS also treats a stage named "Completed"
        # as final, so fill it for those (unfolded) stages too. Capture the same
        # timestamp and actor in the work audit fields.
        if completed:
            completed.sudo().write({
                'date_end': now,
                'ft_completed_by_id': self.env.user.id,
                'ft_work_end_date': now,
            })
        for task in reopened:
            # sudo: the counter is readonly to users, and whoever drags the card
            # back may not have write access to a field they never edit directly.
            task.sudo().write({
                'ft_reopen_count': task.ft_reopen_count + 1,
                'ft_reopened_date': now,
            })
        self._ft_validate_written(vals)
        return res

    def _ft_validate_written(self, vals):
        """Re-run the required-field rules for whatever this write touched.

        These rules cannot be left to their @api.constrains decorators alone,
        for a reason that is easy to miss and silently disables them:
        _validate_fields() runs EVERY constraint method as sudo
        (odoo/orm/models.py, "run constrains just as sudoed computed-stored
        fields"). Each of these checks opens with `if self.env.su: return` so
        that imports and migrations are not blocked — which means that whenever
        the ORM is the caller, the guard sees su and the check returns without
        doing anything.

        create() already worked around this by calling the checks outright. Only
        create() did, so the rules held on a new task and then evaporated: an
        existing task's Estimated could be edited back to 0 and saved. Calling
        them here, from the user's own environment rather than the sudoed one
        the ORM would have handed them, is what makes them hold for an edit too.

        Keyed on what is actually in `vals`, so editing a description or moving
        a stage still does not drag the whole legacy backlog through validation.
        """
        if 'estimated' in vals or 'project_id' in vals:
            self._check_estimated_required()
        if 'user_ids' in vals or 'task_type' in vals:
            self._check_user_story_single_assignee()
        if 'date_deadline' in vals or 'task_source' in vals:
            self._check_deadline_required()
        if any(field in vals for field in (
                'task_type', 'task_source', 'project_id',
                'source_ticket_id', 'unplanned_reason')):
            self._check_task_source_rules()

    @api.constrains(
        'task_type', 'task_source', 'project_id',
        'source_ticket_id', 'unplanned_reason',
    )
    def _check_task_source_rules(self):
        """Validate Task Source and its conditional supporting evidence."""
        # Stored-field recomputations run as superuser during module upgrades.
        # Legacy tasks may not yet have the evidence required by the new rules;
        # normal create/write calls explicitly invoke this method in the real
        # user's environment, so interactive validation remains enforced.
        if self.env.su:
            return

        for task in self:
            if task.task_type == 'user_story' and not task.task_source:
                raise ValidationError(_(
                    "Task Source is required for User Story tasks."
                ))

            if task.task_source == 'planned':
                project = task.project_id
                project_stage = (
                    (project.stage_id.name or '').strip().lower()
                    if project and project.stage_id else ''
                )
                # ``status`` is the legacy selection; stage_id is the active
                # project pipeline used by this database. Honour either so the
                # rule also works during migration from the old field.
                is_discovery = bool(project) and (
                    project_stage == 'discovery'
                    or project.status == 'discovery'
                )
                if not is_discovery:
                    raise ValidationError(_(
                        "A task with Task Source set to Planned can be created "
                        "only while its project is in the Discovery stage."
                    ))

            if task.task_source == 'change_request':
                if not task.source_ticket_id:
                    raise ValidationError(_(
                        "A customer-created Ticket is required when Task Source "
                        "is Change Request."
                    ))
                ticket = task.source_ticket_id
                if ticket.channel != 'portal':
                    raise ValidationError(_(
                        "The Change Request Ticket must be a customer-created "
                        "portal ticket."
                    ))
                if task.project_id and ticket.project_id != task.project_id:
                    raise ValidationError(_(
                        "The selected customer Ticket must belong to the same "
                        "project as the task."
                    ))

            if task.task_source == 'unplanned':
                reason = (task.unplanned_reason or '').strip()
                if len(reason) < UNPLANNED_REASON_MIN_LEN:
                    raise ValidationError(_(
                        "Unplanned Reason is required and must contain at least "
                        "%s characters."
                    ) % UNPLANNED_REASON_MIN_LEN)

    def _check_planned_creation_permission(self):
        """Planned is an initial status reserved for PM, TL and Admin."""
        planned_tasks = self.filtered(
            lambda task: (task.stage_id.name or '').strip().lower() == 'planned'
        )
        if not planned_tasks or self.env.su \
                or self.env.user.has_group('base.group_system'):
            return
        employee = self.env.user.employee_id
        job_name = (
            (employee.sudo().job_id.name or '').strip().lower()
            if employee else ''
        )
        if job_name not in PLANNED_CREATE_JOB_NAMES:
            raise UserError(_(
                "Only a Project Manager, Project Coordinator, Technical Lead "
                "or Administrator can create a task in Planned status."
            ))

    def _check_planned_stage_write(self, target_stage_id):
        """Never allow an existing task to be moved back into Planned."""
        if self.env.su:
            return
        target = self.env['project.task.type'].browse(target_stage_id).exists()
        if not target or (target.name or '').strip().lower() != 'planned':
            return
        moved_tasks = self.filtered(
            lambda task: (task.stage_id.name or '').strip().lower() != 'planned'
        )
        if moved_tasks:
            raise UserError(_(
                "Planned status can be assigned only during task creation. "
                "An existing task cannot be moved back to Planned."
            ))

    def _check_user_story_stage_move(self, target_stage_id):
        """Enforce the User Story workflow and its developer/tester ownership.

        This is server-side deliberately: Kanban drag/drop, the form statusbar,
        imports and direct RPC writes must all obey the same rule.
        """
        if self.env.su or self.env.user.has_group('base.group_system'):
            return

        target = self.env['project.task.type'].browse(target_stage_id).exists()
        if not target:
            raise ValidationError(_("The selected task stage does not exist."))
        target_name = (target.name or '').strip().lower()
        employee = self.env.user.employee_id
        job_name = (
            (employee.sudo().job_id.name or '').strip().lower()
            if employee else ''
        )

        # Project Managers own the workflow and may perform any stage movement,
        # including Testing -> Completed. The separate Planned-stage guard runs
        # before this method, so even master access cannot move an existing task
        # back to Planned.
        if job_name in PROJECT_MANAGER_JOB_NAMES:
            return

        allowed_by_role = {
            'developer': {('planned', 'working'), ('working', 'testing')},
            'tester': {('testing', 'working'), ('testing', 'completed')},
        }
        if job_name in DEVELOPER_JOB_NAMES:
            role = 'developer'
        elif job_name in TESTER_JOB_NAMES:
            role = 'tester'
        else:
            role = None

        for task in self.filtered(lambda item: item.task_type == 'user_story'):
            source_name = (task.stage_id.name or '').strip().lower()
            if source_name == target_name:
                continue
            if (source_name not in USER_STORY_STAGE_NAMES
                    or target_name not in USER_STORY_STAGE_NAMES):
                raise ValidationError(_(
                    "User Story tasks must use this status flow: "
                    "Planned → Working → Testing → Completed."
                ))

            transition = (source_name, target_name)
            if role == 'developer' and self.env.user not in task.user_ids:
                raise UserError(_(
                    "Only a developer assigned to this User Story can move it "
                    "from Planned to Working or from Working to Testing."
                ))
            if not role or transition not in allowed_by_role[role]:
                if target_name == 'completed':
                    raise UserError(_(
                        "Only a Tester can move a User Story from Testing to "
                        "Completed."
                    ))
                if role == 'developer':
                    raise UserError(_(
                        "Developers can move an assigned User Story only from "
                        "Planned to Working or from Working to Testing. They "
                        "cannot skip Testing or move it backwards."
                    ))
                if role == 'tester':
                    raise UserError(_(
                        "Testers can move a User Story only from Testing to "
                        "Completed, or back from Testing to Working for rework."
                    ))
                raise UserError(_(
                    "Only an assigned Developer or a Tester can change the "
                    "status of a User Story."
                ))

    def _check_task_create_permission(self):
        if self.env.su or self.env.user.has_group('base.group_system'):
            return
        employee = self.env.user.employee_id
        job_name = (
            (employee.sudo().job_id.name or '').strip().lower()
            if employee else ''
        )
        if job_name not in TASK_CREATE_JOBS:
            raise UserError(_(
                "You are not allowed to create tasks. Only a Technical Lead, "
                "Project Manager or Project Coordinator can create tasks."
            ))

    # Estimate and deadline are required on every task from here on. They are
    # enforced as constraints rather than with `required=True` on the fields,
    # for two reasons that both matter:
    #
    #   estimated is a Float, so it is never NULL — it defaults to 0.0 and
    #       `required=True` would be satisfied by a zero, enforcing nothing. The
    #       real rule is "> 0", which only a constraint can express.
    #   date_deadline would take a NOT NULL column, and 6,936 of the 7,029 active
    #       tasks have no deadline — the upgrade would simply fail.
    #
    # A constraint also limits the blast radius on that legacy data: it fires on
    # create, and on write only when the field itself is being changed. Editing
    # an old task's description or moving its stage does not trip it, so the
    # backlog stays workable while everything new is complete.
    @api.constrains('estimated')
    def _check_estimated_required(self):
        # Superuser only: imports, migrations and scheduled jobs must not be
        # blocked. A plain administrator IS held to it, like task creation.
        if self.env.su:
            return
        for task in self:
            # Only tasks that belong to a project. A task with no project is a
            # private to-do that no project metric reads, so demanding an
            # estimate on it blocks the user for nothing.
            if task.project_id and task.estimated <= 0:
                raise ValidationError(_(
                    "Estimated time is required.\n\n"
                    "Task: %s\n\n"
                    "Enter how long this task is expected to take. Without it "
                    "the task cannot be counted in Delivery Efficiency, and it "
                    "lands in the Not Estimated figure on the dashboard."
                ) % (task.name or ''))

    @api.constrains('date_deadline', 'task_source')
    def _check_deadline_required(self):
        if self.env.su:
            return
        now = fields.Datetime.now()
        minimum_planned_deadline = now + timedelta(hours=24)
        is_admin = self.env.user.has_group('base.group_system')
        for task in self:
            if not task.date_deadline:
                raise ValidationError(_(
                    "Deadline is required.\n\n"
                    "Task: %s\n\n"
                    "Set the date this task is due. Without it the task can "
                    "never be judged on time or late — it is excluded from "
                    "On-Time Delivery and counted as Delivered Without Deadline."
                ) % (task.name or ''))
            if task.date_deadline <= now:
                raise ValidationError(_(
                    "Deadline must be a future date and time.\n\n"
                    "Task: %s\n\n"
                    "Select a Deadline later than the current date and time."
                ) % (task.name or ''))
            if (task.task_source in ('planned', 'unplanned')
                    and not is_admin
                    and task.date_deadline < minimum_planned_deadline):
                raise ValidationError(_(
                    "Deadline must be at least 24 hours from the current time "
                    "for Planned and Unplanned tasks.\n\n"
                    "Task: %s"
                ) % (task.name or ''))

    @api.constrains('task_type', 'user_ids')
    def _check_user_story_single_assignee(self):
        """A User Story is owned by one person.

        Only User Stories. Internal and external calls are routinely worked by
        a pair and are left alone.

        Superuser is exempt for the same reason the other checks exempt it —
        imports and automation must not be blocked — but note this fires on
        WRITE as well as create, so the rule reaches the tasks that already
        exist: reassigning one of them means bringing it down to a single
        assignee at the same time.
        """
        if self.env.su:
            return
        for task in self:
            if task.task_type == 'user_story' and len(task.user_ids) > 1:
                raise ValidationError(_(
                    "A User Story can have only one assignee.\n\n"
                    "Task: %s\n"
                    "Currently assigned to: %s\n\n"
                    "Leave a single assignee, or change the Task Type if this "
                    "work really is shared."
                ) % (task.name or '', ', '.join(task.user_ids.mapped('name'))))

    @api.constrains('name')
    def _check_task_title_length(self):
        # #2 - Task title must be at least TASK_TITLE_MIN_LEN characters.
        for task in self:
            if task.name and len(task.name.strip()) < TASK_TITLE_MIN_LEN:
                raise ValidationError(_(
                    "Task title must be at least %s characters long."
                ) % TASK_TITLE_MIN_LEN)

    @api.depends('timesheet_ids.ft_is_rework', 'timesheet_ids.unit_amount')
    def _compute_ft_rework_hours(self):
        for task in self:
            task.ft_rework_hours = round(sum(
                line.unit_amount for line in task.timesheet_ids
                if line.ft_is_rework
            ), 2)

    @api.model
    def ft_get_final_stage_ids(self):
        """Public wrapper so the web client can ask which stages are final.

        The status-bar confirmation needs this: it used to decide "is this a
        completion?" from the item's own ``isFolded`` flag, which is False on
        every stage in this database, so the dialog never once appeared. Odoo
        refuses RPC to names beginning with an underscore, hence the wrapper
        rather than exposing _ft_final_stage_ids directly.
        """
        return self._ft_final_stage_ids()

    @api.model
    def _ft_final_stage_ids(self):
        """Ids of every task stage that counts as DELIVERED.

        THE single answer to "is this stage finished" for the whole PMS: folded
        stages, plus any stage named in COMPLETED_STAGE_NAMES whether or not
        somebody remembered to tick Folded.

        Resolved to ids rather than filtering on ``stage_id.name`` inside each
        domain, because the stage name is a translated (jsonb) column — comparing
        it in a domain is slower and answers differently per language, and the
        same reasoning already governs the project-stage lookups in
        ft_project_dashboard.

        Archived stages are included: a task can still sit in one, and leaving
        them out would make that work vanish from delivered and open alike.
        """
        return self.env['project.task.type'].with_context(
            active_test=False
        ).search([
            '|',
            ('fold', '=', True),
            ('name', 'in', list(COMPLETED_STAGE_NAMES)),
        ]).ids

    # stage_id.name is in the depends because the set of final stages now turns
    # on the name too: renaming a stage to or from "Completed" has to recompute
    # the tasks sitting in it, or their completion date would silently disagree
    # with what the metrics count.
    @api.depends('date_end', 'date_last_stage_update',
                 'stage_id.fold', 'stage_id.name')
    def _compute_ft_completion_date(self):
        """The delivery date, with a fallback for a missing ``date_end``.

        Odoo stamps ``date_end`` in ``update_date_end()`` only when ``stage_id``
        is written, and writes False whenever the target stage is not folded. So
        a task that entered Completed while that stage was still unfolded — the
        flag being ticked afterwards — sits in a folded stage forever with an
        empty date_end. Filtering delivery on date_end dropped exactly those
        tasks: not counted as delivered, and not counted as open either, because
        their stage IS folded. Silently invisible in both directions.

        ``date_last_stage_update`` is written by the same core code path on every
        stage change, so for those tasks it holds the moment they were completed.
        It is the fallback, not the primary: a reopened-then-reclosed task can
        have a later stage change than its date_end, and date_end is the more
        precise answer whenever it exists.

        Stored so it can be searched and date-ranged, and so that upgrading this
        module backfills every historical task in one recompute.
        """
        # Resolved once for the whole recordset: this compute runs over every
        # task in the database on upgrade.
        final_ids = set(self._ft_final_stage_ids())
        for task in self:
            task.ft_completion_date = (
                (task.date_end or task.date_last_stage_update)
                if task.stage_id.id in final_ids else False
            )

    @api.depends('ft_completion_date', 'date_deadline')
    def _compute_ft_timeline_status(self):
        """Classify completed tasks using the PMS's calendar-day deadline rule."""
        for task in self:
            if not task.ft_completion_date or not task.date_deadline:
                task.ft_timeline_status = False
            elif (task._ft_local_date(task.ft_completion_date)
                  <= task._ft_local_date(task.date_deadline)):
                task.ft_timeline_status = 'on_time'
            else:
                task.ft_timeline_status = 'overdue'

    # ------------------------------------------------------------------
    # On-Time Delivery
    #
    # THE single definition of "delivered" and "on time" for the whole PMS.
    # The project fields (project.project) and the dashboard both call these,
    # so an all-time figure on a project and a date-filtered figure on the
    # dashboard can never disagree about what they are counting.
    # ------------------------------------------------------------------
    @api.model
    def _ft_delivery_domain(self, extra=None, date_from=None, date_to=None):
        """Domain for DELIVERED tasks.

        Delivered = sits in a folded stage (Completed) and carries a completion
        date. A task reopened and closed again counts by its latest completion.

        Completion is read from ``ft_completion_date``, NOT raw ``date_end``:
        Odoo leaves date_end empty on any task that entered a stage before that
        stage was marked Folded, and filtering on it made those tasks vanish from
        the delivered count while their folded stage also kept them out of the
        open count. See ``_compute_ft_completion_date``.

        Keyed off the STAGE, not `state`. Stages do not set state in Odoo 18
        (see the note in views/project_task_views.xml), so counting state
        '1_done' would miss almost everything this DB actually completes.

        Cancelled work is excluded: "Cancelled" is a folded stage in some stage
        sets, and a cancelled task is not a delivery. `state` is only ever set to
        '1_canceled' deliberately, so it is safe as an exclusion even though it
        is unreliable as an inclusion.

        The date range filters on the completion date — i.e. what was DELIVERED
        in the period, not what was created in it.
        """
        dom = [
            ('stage_id', 'in', self._ft_final_stage_ids()),
            ('state', '!=', '1_canceled'),
            ('ft_completion_date', '!=', False),
        ]
        if date_from:
            dom.append(('ft_completion_date', '>=', str(date_from)))
        if date_to:
            # ft_completion_date is a Datetime; span the whole closing day.
            dom.append(('ft_completion_date', '<=', str(date_to) + ' 23:59:59'))
        return dom + (extra or [])

    @api.model
    def _ft_local_date(self, value):
        """A stored UTC value as a calendar date in the reader's timezone.

        Both the completion date and ``date_deadline`` are Datetimes held in UTC, so
        taking ``.date()`` straight off them would bucket work by the UTC day.
        For anything finished late in the local evening that is the WRONG day
        (20:00 UTC is already tomorrow in IST), which would mark on-time work
        late. Converting first puts both sides on the user's calendar.
        """
        if not value:
            return None
        if isinstance(value, datetime):
            return fields.Datetime.context_timestamp(self, value).date()
        return value

    @api.model
    def _ft_on_time_aggregate(self, tasks):
        """Aggregate a recordset of DELIVERED tasks into on-time figures.

        Tasks with no deadline cannot be judged, so they are excluded from the
        denominator and reported separately as ``no_deadline`` — counting them
        as on-time would hand a perfect score to any project that simply never
        sets deadlines.

        On time is judged by CALENDAR DAY, not to the minute. ``date_deadline``
        is a Datetime, so a deadline entered as a day is stored carrying a
        time-of-day; comparing the raw timestamps made a task finished at 13:12
        on its own due date "late" against a 13:00 stamp nobody chose. A
        deadline of the 23rd means end of the 23rd, so any completion on that
        date counts as on time.

        ``rate`` is None (not 0.0) when nothing measurable was delivered, so the
        UI shows "N/A" instead of a 0% that reads as a failure.
        """
        split = self._ft_on_time_split(tasks)
        on_time = len(split['on_time'])
        late = len(split['late'])
        completed = len(tasks)
        measurable = on_time + late
        return {
            'completed': completed,
            'measurable': measurable,
            'no_deadline': completed - measurable,
            'on_time': on_time,
            'late': late,
            'rate': round(on_time / measurable * 100, 2) if measurable else None,
        }

    @api.model
    def _ft_on_time_split(self, tasks):
        """DELIVERED tasks split into on-time and late ids.

        The judgement itself, factored out of ``_ft_on_time_aggregate`` so a
        dashboard card can open exactly the tasks behind its number. Counting
        and listing therefore run the same comparison — a drill-down cannot
        show a different set from the figure that was clicked.

        Tasks with no deadline appear in neither list: they cannot be judged.
        """
        on_time, late = [], []
        for task in tasks:
            if not task.date_deadline:
                continue
            if self._ft_local_date(task.ft_completion_date) <= self._ft_local_date(task.date_deadline):
                on_time.append(task.id)
            else:
                late.append(task.id)
        return {'on_time': on_time, 'late': late}

    @api.model
    def _ft_efficiency_aggregate(self, tasks):
        """Delivery Efficiency for a recordset of DELIVERED tasks.

        (Estimated / Actual) x 100. Target 90-110%: under 90 means the work took
        materially longer than estimated, over 110 means the estimate was padded.

        Only tasks carrying BOTH an estimate and logged time are counted. A task
        estimated at 8h with no timesheet would otherwise divide by zero, and a
        task with time logged but no estimate would drag the ratio toward zero
        while saying nothing about estimation quality. ``unestimated`` reports
        how much work was skipped, so a flattering ratio drawn from three tasks
        out of two hundred is visible rather than trusted.

        Estimated is the custom ``estimated`` field, NOT core ``allocated_hours``.
        ft_task_hours_tracker hides the core Allocated Time block from the task
        form, so ``allocated_hours`` is unreachable in this workflow and reading
        it made the whole metric permanently unmeasurable. ``estimated`` is the
        field the task form actually exposes. Actual stays ``effective_hours``
        (the stored sum of timesheet lines).
        """
        measurable = tasks.filtered(
            lambda t: t.estimated > 0 and t.effective_hours > 0
        )
        estimated = sum(measurable.mapped('estimated'))
        actual = sum(measurable.mapped('effective_hours'))
        return {
            'estimated_hours': round(estimated, 2),
            'actual_hours': round(actual, 2),
            'measurable': len(measurable),
            'unestimated': len(tasks) - len(measurable),
            # None, not 0.0, when nothing is measurable: 0% efficiency reads as
            # catastrophic, while the truth is that nobody estimated anything.
            'rate': round(estimated / actual * 100, 2) if actual else None,
        }

    @api.model
    def _ft_rework_aggregate(self, tasks):
        """Rework figures for a recordset of DELIVERED tasks.

        Two complementary measures, because "how often" and "how expensive" are
        different questions and a team can score well on one while failing the
        other:

          rate       (Tasks reopened / Total delivered) x 100. Target 10% or
                     below. Counts TASKS reopened at least once, not reopen
                     events, so one task bounced five times cannot push it past
                     100%.
          hours_rate (Rework hours / Total hours) x 100 — the share of effort
                     that went into redoing delivered work. A single task
                     reopened once but costing eighty hours barely moves the
                     count rate while dominating this one.

        Rework hours come from the per-line ft_is_rework flag, stamped when the
        time was entered, so they measure the effort that followed a reopen
        rather than everything ever logged on a task that was reopened later.
        """
        completed = len(tasks)
        reworked = len(tasks.filtered(lambda t: t.ft_reopen_count > 0))
        rework_hours = sum(tasks.mapped('ft_rework_hours'))
        total_hours = sum(tasks.mapped('effective_hours'))
        return {
            'completed': completed,
            'reworked': reworked,
            'rate': round(reworked / completed * 100, 2) if completed else None,
            'rework_hours': round(rework_hours, 2),
            # None rather than 0 when nothing was logged: 0% would read as "no
            # rework" when the truth is that there is nothing to measure.
            'hours_rate': (round(rework_hours / total_hours * 100, 2)
                           if total_hours else None),
        }

    @api.model
    def _ft_open_domain(self, extra=None):
        """Domain for OPEN tasks — the complement of ``_ft_delivery_domain``.

        Open = not in a folded stage, i.e. still somewhere in Planned / Working /
        Testing. Keyed off the stage for the same reason delivery is: stages do
        not set `state`, so "not in a closed state" would call almost everything
        open, including finished work.
        """
        # Written as the explicit complement of _ft_final_stage_ids rather than
        # `stage_id.fold = False`, so open and delivered stay exact opposites of
        # one another and no task can fall into both or neither.
        #
        # The stageless leaf is deliberate: a task with no stage at all used to be
        # counted as neither open nor delivered, because traversing an empty
        # many2one matches nothing — 173 active tasks were invisible to both
        # figures on the production restore. It is certainly not delivered, so it
        # is open.
        return [
            '|',
            ('stage_id', '=', False),
            ('stage_id', 'not in', self._ft_final_stage_ids()),
        ] + (extra or [])

    @api.model
    def _ft_overdue_open_domain(self, extra=None):
        """Domain for open tasks already past their deadline.

        The companion to the on-time rate, and the reason to trust it. The rate
        only looks at work that finished, so a task six months late and still
        open never appears in it — a team could score 100% by never closing its
        late work. This is what stops that hiding. It is a snapshot of now, so
        it is deliberately NOT filtered by the report's date range.
        """
        return self._ft_open_domain([
            ('date_deadline', '!=', False),
            ('date_deadline', '<', fields.Datetime.now()),
        ] + (extra or []))

    @api.model
    def _ft_overdue_open_count(self, extra=None):
        """Count of open, past-deadline tasks. See ``_ft_overdue_open_domain``."""
        return self.search_count(self._ft_overdue_open_domain(extra))

    @api.model
    def _ft_delivery_kpis(self, tasks):
        """All three delivery KPIs for one recordset of DELIVERED tasks.

        One place to add a fourth. Efficiency and rework keys are prefixed so
        they cannot collide with the on-time keys they are merged into.
        """
        stats = self._ft_on_time_aggregate(tasks)
        efficiency = self._ft_efficiency_aggregate(tasks)
        rework = self._ft_rework_aggregate(tasks)
        stats.update({
            'efficiency_rate': efficiency['rate'],
            'estimated_hours': efficiency['estimated_hours'],
            'actual_hours': efficiency['actual_hours'],
            'unestimated': efficiency['unestimated'],
            'rework_rate': rework['rate'],
            'reworked': rework['reworked'],
            'rework_hours': rework['rework_hours'],
            'rework_hours_rate': rework['hours_rate'],
        })
        return stats

    @api.model
    def _ft_on_time_stats(self, extra=None, date_from=None, date_to=None):
        """All delivery KPIs for any scope. See ``_ft_delivery_domain``."""
        tasks = self.search(self._ft_delivery_domain(extra, date_from, date_to))
        stats = self._ft_delivery_kpis(tasks)
        stats['overdue_open'] = self._ft_overdue_open_count(extra)
        return stats

    @api.model
    def _ft_on_time_stats_by_project(self, project_ids, date_from=None, date_to=None):
        """``{project_id: stats}`` — one search for the whole set, not one each."""
        tasks = self.search(self._ft_delivery_domain(
            [('project_id', 'in', list(project_ids))], date_from, date_to))
        # Group ids and browse once per project: repeatedly unioning recordsets
        # (recs |= task) rebuilds the set on every step.
        ids_by_project = {}
        for task in tasks:
            ids_by_project.setdefault(task.project_id.id, []).append(task.id)
        return {
            pid: self._ft_delivery_kpis(self.browse(ids))
            for pid, ids in ids_by_project.items()
        }

    @api.model
    def _ft_overdue_open_count_by_project(self, project_ids):
        """``{project_id: count}`` of open, past-deadline tasks. One query."""
        groups = self.read_group(
            self._ft_overdue_open_domain([('project_id', 'in', list(project_ids))]),
            ['id'], ['project_id'], lazy=False,
        )
        return {
            g['project_id'][0]: g['__count']
            for g in groups if g.get('project_id')
        }
