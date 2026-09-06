from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

# Job positions (hr.job names, lower-cased) allowed to change the project status.
PM_JOB_NAMES = ('project manager', 'project coordinator', 'project cordinator')

# The two project stages that divide the Task Source bands, matched on the
# lower-cased English stage name. Everything up to and including Discovery is
# Planned work, everything from UAT onwards is a Change Request, and what lies
# between the two is Unplanned.
#
# Named rather than hard-coded by id or sequence number because sequences get
# renumbered whenever somebody drags a column in the project pipeline, and ids
# differ between databases. Aliases are listed for UAT because the stage is
# spelled out in full on this database ("User Acceptance") while the rule that
# drives it is always spoken as UAT.
DISCOVERY_STAGE_NAMES = ('discovery', 'disc')
UAT_STAGE_NAMES = ('user acceptance', 'user acceptance testing', 'uat')


# ---------------------------------------------------------------------------
# Project-level Stage Validation Framework (task points 1-12)
# ---------------------------------------------------------------------------
# Validation is applied to Project-level stage movement (project.project.stage,
# the Kanban status bar / stage_id), never to task stages. See
# InheritProjectProject.write for the enforcement and _compute_ft_overdue for
# the Overdue signal.
#
# Every rule is keyed on a canonical stage KEY derived from the stage NAME, not
# on xml-id or sequence. The lifecycle stages are runtime records: their ids
# differ per database, their sequence numbers get renumbered the moment a column
# is dragged in the pipeline, and their names carry a code plus a label
# ("DISC - Discovery"). Classifying by name under a forced English lang is the
# same approach _ft_source_boundaries already relies on for the Task Source
# bands, so the two can never disagree about which stage is which.
#
# Each marker entry is (canonical key, tuple of accepted markers). A marker
# containing a space is tested as a substring of the normalised name; a
# single-word marker is tested as a whole word, so the short code "dev" matches
# "DEV - Development" while never matching the middle of an unrelated word.
# Order is most-specific first for the names that could otherwise collide.
FT_STAGE_MARKERS = (
    ('data', ('data upload', 'data')),
    ('disc', ('discovery', 'disc')),
    ('dev', ('development', 'dev')),
    ('reg', ('regression', 'reg')),
    ('srv', ('sandbox review', 'sandbox', 'srv')),
    ('uat', ('user acceptance testing', 'user acceptance', 'uat')),
    ('tra', ('training', 'tra')),
    ('support', ('support',)),
    ('hold', ('on hold', 'hold')),
    ('amc', ('amc',)),
    ('closed', ('closed', 'close')),
)

# canonical stage key -> (date field on project.project, human label). The date
# named here must already be set before the project may ENTER that stage; a move
# with the date still missing is blocked with a clear message (task points 2-9).
# 'reg' and 'hold' carry no requirement on purpose: entering Regression has none
# defined, and a project may be put On Hold at any point in its life.
FT_STAGE_DATE_REQUIREMENTS = {
    'disc': ('kick_start_meeting_date', 'Kick-off Date'),
    'dev': ('brd_approval_date', 'BRD Approval Date'),
    'srv': ('ft_regression_date', 'Regression Date'),
    'uat': ('sandbox_review_date', 'Sandbox Review Date'),
    'data': ('uat_start_date', 'UAT Start Date'),
    'tra': ('ft_training_date', 'Training Date'),
    'support': ('support_start_date', 'Support Start Date'),
    'amc': ('go_live_date', 'Go Live Date'),
    'closed': ('go_live_date', 'Go Live Date'),
}

# The forward delivery pipeline, in order, used by the Overdue check only. AMC,
# CLOSED and HOLD are deliberately excluded: they are terminal or branch states
# rather than scheduled milestones, and since go_live_date gates both AMC and
# CLOSED, including them would flag every live project as overdue for whichever
# end state it did not take.
FT_OVERDUE_KEYS = ('disc', 'dev', 'srv', 'uat', 'data', 'tra', 'support')


class ProjectProjectStage(models.Model):
    _inherit = 'project.project.stage'

    @api.model
    def _ft_classify_stage_name(self, name):
        """Canonical lifecycle key for a stage name, or False.

        Reads the English name (callers force lang='en_US') so a translated
        pipeline classifies identically for every user. Non-alphanumerics are
        flattened to spaces first, so "DISC - Discovery", "DISC / Discovery" and
        "DISC   Discovery" all resolve the same.
        """
        normalized = ''.join(
            c if c.isalnum() else ' ' for c in (name or '').lower()
        )
        words = set(normalized.split())
        for key, markers in FT_STAGE_MARKERS:
            for marker in markers:
                if ' ' in marker:
                    if marker in normalized:
                        return key
                elif marker in words:
                    return key
        return False

    def _ft_stage_key(self):
        self.ensure_one()
        return self._ft_classify_stage_name(
            self.with_context(lang='en_US').name
        )

    @api.model
    def _ft_lifecycle_stage_map(self):
        """{canonical key: the earliest live stage carrying that key}.

        Archived stages are excluded (default search) and, among the live ones,
        the earliest in pipeline order wins the key. This mirrors
        _ft_source_boundaries so the retired pre-lifecycle stages can never
        shadow the current ones.
        """
        result = {}
        for stage in self.with_context(lang='en_US').search([], order='sequence, id'):
            key = self._ft_classify_stage_name(stage.name)
            if key and key not in result:
                result[key] = stage
        return result

    @api.model
    def _ft_stage_sort_key(self, stage):
        """Where a stage sits in the pipeline, as a comparable key.

        (sequence, id), which is the model's own ``_order``. The id is part of
        the key and not a tiebreak of convenience: this database has two stages
        on sequence 10 (Closed and To Do), so comparing on sequence alone makes
        their order undefined and the Task Source of anything sitting in them
        flip about depending on which row Postgres returned first.
        """
        return (stage.sequence, stage.id)

    @api.model
    def _ft_source_boundaries(self):
        """The Discovery and UAT stage records, or empty recordsets.

        Resolved by reading the stages and comparing in Python under a forced
        ``lang='en_US'`` rather than with a ``('name', '=', ...)`` domain. The
        stage name is a translated jsonb column, so a domain answers differently
        per user language — a French-speaking PM would silently get no match and
        every task they created would come out with no source at all.

        Archived stages are excluded on purpose, and this is load-bearing.
        ft_project_lifecycle replaces the old pipeline with a new set of stage
        RECORDS and archives the originals rather than deleting them, because
        20,595 timesheet snapshots point at them. The retired "Discovery" and
        "User Acceptance" stages sit at sequences 1 and 5, ahead of every new
        stage; left in the search they would keep winning the match, put the
        UAT boundary below the whole new lifecycle, and stamp every task
        created from then on as a Change Request — the one value that must
        never be guessed, since it is what change-request billing is argued
        from.
        """
        stages = self.with_context(lang='en_US').search([])
        discovery = uat = self.browse()
        for stage in stages:
            name = (stage.name or '').strip().lower()
            if name in DISCOVERY_STAGE_NAMES and not discovery:
                discovery = stage
            elif name in UAT_STAGE_NAMES and not uat:
                uat = stage
        return discovery, uat


class InheritProjectProject(models.Model):
    _inherit = 'project.project'

    # The Project Type stamped on a project created server-side with none given
    # (see the ft_project_type field and create() below). Held on the model
    # rather than as a module constant because ft_project_lifecycle needs the
    # same answer one step EARLIER in the MRO: it is loaded after this module,
    # so its create() runs first and has to know the type to pick the right
    # stage pipeline. Without a shared answer a sudo'd creation would be
    # stage-homed against every stage in the database and then rejected by
    # _check_stage_for_type once the type landed.
    FT_FALLBACK_PROJECT_TYPE = 'implementation'

    # What KIND of engagement this project is, as distinct from how far along
    # it is. The two were conflated in the project pipeline before this field
    # existed: AMC and General were stages sitting alongside Development and
    # Closed, so "an implementation project currently in Support" could not be
    # told apart from "an AMC contract", and a project's type became
    # unreadable the moment it moved to Closed. Type is stable for the life of
    # the project; stage_id keeps moving.
    #
    # Required, because the column must never hold NULL: rules that branch on
    # the type would let a NULL fall through every branch silently instead of
    # failing loudly.
    #
    # Deliberately NO default. It used to default to 'implementation', which
    # meant every project created through the UI was silently classified before
    # anybody looked at the field, and the wrong classification was only found
    # later — by which time the project had already been routed down the
    # Implementation stage pipeline and had a Task Source rule applied to its
    # tasks. Leaving it blank makes the web client refuse to save the form until
    # somebody chooses, so the type is a decision taken at creation rather than
    # a value inherited by accident.
    #
    # Server-side creation has no form to enforce that, so create() below stamps
    # a fallback for superuser creates only — module install, migrations,
    # hr_timesheet's per-company "Internal" project and sale_timesheet's
    # project-from-sale-order all run sudo'd and would otherwise abort. A plain
    # administrator working in the UI is NOT superuser, so they still have to
    # pick.
    ft_project_type = fields.Selection(
        [
            ('implementation', 'Implementation'),
            ('amc', 'AMC'),
            ('general', 'General'),
        ],
        string='Project Type',
        required=True,
        tracking=True,
        help="Implementation: a client delivery engagement, from Discovery "
             "through go-live and its warranty/support window.\n"
             "AMC: an annual maintenance contract, normally renewed per year.\n"
             "General: internal or non-delivery work — bench activity, "
             "training, pre-sales, demos and administration.",
    )

    # The other side of cus.module.project_ids — the modules this project
    # offers. Editing it from either end writes the same rows, so a module can
    # be attached to a project from whichever form the user happens to be on.
    module_ids = fields.Many2many(
        'cus.module',
        relation='cus_module_project_project_rel',
        column1='project_project_id',
        column2='cus_module_id',
        string='Modules',
        help='Modules available to tasks in this project. The Module field on '
             'a task offers only what is listed here.',
    )

    def _ft_task_source(self):
        """The Task Source a task created in this project should carry.

        Discovery (and anything before it) is work that was Planned when the
        project was scoped; the build stages that follow are Unplanned; from UAT
        onwards the client has seen the product, so new work is a Change
        Request.

        That banding is the Implementation lifecycle's. AMC has no rule defined
        yet and General states Planned outright; see the type checks below.

        Returns False rather than guessing when the pipeline cannot be read —
        no stage on the project, or no UAT stage configured at all. An empty
        Task Source is visibly missing and gets filled in; a wrongly confident
        one is never questioned, and this field is what change-request billing
        is argued from.
        """
        self.ensure_one()
        if not self.stage_id:
            return False
        # Only the Implementation lifecycle has the DISC..UAT bands read below,
        # and it is the one project type a Change Request can come out of: the
        # source means "the client had already signed this off and has now
        # asked for something different", which presupposes a delivery that was
        # signed off. AMC and General run Started -> Working -> Completed, where
        # no stage answers "was this scoped up front".
        #
        # AMC returns False — no default, so the person entering the task
        # chooses. THE AMC RULE IS NOT YET DEFINED; this is a deliberate blank
        # awaiting it, not an omission. It previously returned 'change_request',
        # carried over from the old pipeline where the AMC stage happened to sit
        # past the UAT boundary. That was an accident of sequence numbers with a
        # real cost: every task in a maintenance contract came out as a Change
        # Request and so demanded a customer portal ticket before it could be
        # saved, whether or not any customer had raised one. An empty Task
        # Source is visibly missing and gets filled in; a wrongly confident one
        # is never questioned, and this field is what change-request billing is
        # argued from. Fill this in when the rule arrives.
        if self.ft_project_type == 'amc':
            return False
        # General keeps Planned, reproducing what the old pipeline gave it (the
        # General stage sat on sequence 0, at or before Discovery). Internal
        # work has no customer to change its mind, so Planned is the honest
        # reading and it demands no evidence.
        if self.ft_project_type == 'general':
            return 'planned'
        Stage = self.env['project.project.stage']
        discovery, uat = Stage._ft_source_boundaries()
        if not uat:
            return False
        here = Stage._ft_stage_sort_key(self.stage_id)
        if here >= Stage._ft_stage_sort_key(uat):
            return 'change_request'
        # Without a Discovery stage there is no boundary between planned and
        # unplanned work, so everything short of UAT is treated as unplanned —
        # the weaker claim of the two, and the one that does not assert work was
        # scoped up front when nothing says it was.
        if discovery and here <= Stage._ft_stage_sort_key(discovery):
            return 'planned'
        return 'unplanned'

    # ------------------------------------------------------------------
    # Stage Validation Framework helpers (task points 1-12)
    # ------------------------------------------------------------------
    def _ft_stage_entry_requirement(self, stage):
        """(date field, human label) the given stage requires on entry, or None.

        Independent of which project it is asked about — the rule is a property
        of the target stage — so it is safe to call on a multi-record set.
        """
        if not stage:
            return None
        return FT_STAGE_DATE_REQUIREMENTS.get(stage._ft_stage_key()) or None

    def _ft_check_stage_entry_dates(self, target_stage, vals):
        """Block a move into ``target_stage`` when its required date is missing.

        The date may be supplied in the very same write (a person filling the
        date and dragging the card together), so the incoming ``vals`` is
        consulted before the stored value. A project already sitting in the
        target stage is skipped, so an unrelated write that happens to re-state
        stage_id never trips the rule.
        """
        requirement = self._ft_stage_entry_requirement(target_stage)
        if not requirement:
            return
        field_name, label = requirement
        for project in self:
            if project.stage_id.id == target_stage.id:
                continue
            value = vals[field_name] if field_name in vals else project[field_name]
            if not value:
                raise UserError(_(
                    "Cannot move project '%(project)s' into the '%(stage)s' "
                    "stage: %(label)s is required. Please set the %(label)s "
                    "before moving the project to this stage."
                ) % {
                    'project': project.display_name,
                    'stage': target_stage.name,
                    'label': label,
                })

    def _ft_overdue_reasons(self, stage_map=None):
        """Human reasons this project is behind schedule (possibly empty).

        A milestone is overdue when its date has passed but the project has not
        yet reached the stage that date gates. Stage order is compared with the
        model's own (sequence, id) key, so two stages sharing a sequence still
        order deterministically.
        """
        self.ensure_one()
        Stage = self.env['project.project.stage']
        if stage_map is None:
            stage_map = Stage._ft_lifecycle_stage_map()
        today = fields.Date.context_today(self)
        here = Stage._ft_stage_sort_key(self.stage_id) if self.stage_id else None
        reasons = []
        for key in FT_OVERDUE_KEYS:
            field_name, label = FT_STAGE_DATE_REQUIREMENTS[key]
            due = self[field_name]
            target = stage_map.get(key)
            if not due or not target:
                continue
            reached = here is not None and here >= Stage._ft_stage_sort_key(target)
            if due < today and not reached:
                reasons.append(_(
                    "%(label)s (%(date)s) has passed but the project has not "
                    "reached %(stage)s"
                ) % {'label': label, 'date': due, 'stage': target.name})
        return reasons

    @api.depends('stage_id', 'kick_start_meeting_date', 'brd_approval_date',
                 'ft_regression_date', 'sandbox_review_date', 'uat_start_date',
                 'ft_training_date', 'support_start_date')
    def _compute_ft_overdue(self):
        stage_map = self.env['project.project.stage']._ft_lifecycle_stage_map()
        for project in self:
            reasons = project._ft_overdue_reasons(stage_map=stage_map)
            project.ft_is_overdue = bool(reasons)
            project.ft_overdue_reason = '; '.join(reasons)

    def _search_ft_is_overdue(self, operator, value):
        if operator not in ('=', '!='):
            raise UserError(_("Unsupported operator for the Overdue filter."))
        want_overdue = bool(value)
        if operator == '!=':
            want_overdue = not want_overdue
        stage_map = self.env['project.project.stage']._ft_lifecycle_stage_map()
        overdue_ids = [
            project.id
            for project in self.sudo().search([])
            if project._ft_overdue_reasons(stage_map=stage_map)
        ]
        return [('id', 'in' if want_overdue else 'not in', overdue_ids)]

    # The project-level counterpart of the task's `estimated` field: the sum of
    # every task's Estimated hours, the way Actual Hours (effective_hours) is the
    # sum of every timesheet. Stored so the project list can sort and group on it.
    # `tasks`, not `task_ids`: core filters task_ids to is_closed = False, which
    # would silently drop the estimate of every finished task.
    estimated = fields.Float(
        string='Estimated Time',
        compute='_compute_estimated',
        store=True,
        readonly=True,
        help='Sum of the Estimated hours of every task in this project, '
             'closed tasks included.',
    )

    architect_id = fields.Many2one('res.users', string='Architect')
    ba_id = fields.Many2one('res.users', string='BA')
    pm_id = fields.Many2one('res.users', string='PM')
    brd_approval_date = fields.Date(string='BRD Approval Date')
    brd_submission_date = fields.Date(string='BRD Submission Date')
    go_live_date = fields.Date(string='Go Live Date')
    # end_date = fields.Date(string='End Date')
    kick_start_meeting_date = fields.Date(string='Kick Start Meeting Date')
    sandbox_review_date = fields.Date(string='Sandbox Review Date')
    # start_date = fields.Date(string='Start Date')
    support_start_date = fields.Date(string='Support Start Date')
    uat_start_date = fields.Date(string='UAT Start Date')
    warranty_end_date = fields.Date(string='Warranty End Date')
    # Two milestone dates the Stage Validation Framework needs that had no home
    # before: Regression gates entry to Sandbox Review (SRV) and Training gates
    # entry to the Training (TRA) stage. Optional Date columns, created on module
    # update; no migration is needed because nothing reads them until set.
    ft_regression_date = fields.Date(
        string='Regression Date',
        tracking=True,
        help='Date regression testing was completed. Required before the '
             'project can be moved into the Sandbox Review (SRV) stage.',
    )
    ft_training_date = fields.Date(
        string='Training Date',
        tracking=True,
        help='Date client training was delivered or scheduled. Required before '
             'the project can be moved into the Training (TRA) stage.',
    )

    # Overdue signal (task points 11-12). Computed, not stored: it turns on
    # today's date, which no @api.depends can invalidate on, so it is recomputed
    # on every read and always current. A search method backs the "Overdue"
    # filter in the Projects search view.
    ft_is_overdue = fields.Boolean(
        string='Overdue',
        compute='_compute_ft_overdue',
        search='_search_ft_is_overdue',
        help='A required milestone date has already passed while the project is '
             'still short of the stage that date gates.',
    )
    ft_overdue_reason = fields.Char(
        string='Overdue Reason',
        compute='_compute_ft_overdue',
        help='Which milestone(s) the project is running behind, and the stage '
             'it should have reached by now.',
    )
    comments = fields.Text(string='Comments')
    development = fields.Text(string='Development')
    payment_terms = fields.Text(string='Payment Terms')
    payment_terms_id = fields.Many2one('account.payment.term',string='Payment Terms')
    user_name = fields.Char(string='User Name')
    password = fields.Char(string='Password')
    poc_email = fields.Char(string='POC Email')
    poc_mobile = fields.Char(string='POC Mobile')
    short_code = fields.Char(string='Short Code', help='Unique, case insensitive')
    hourly_billing_rate = fields.Monetary(string='Hourly Billing Rate', currency_field='currency_id')
    hourly_cost = fields.Monetary(string='Hourly Cost', currency_field='currency_id')
    hours_balance = fields.Float(string='Hours Balance')
    hours_est_pm = fields.Float(string='Hours Est PM')
    hours_est_qa = fields.Float(string='Hours Est QA')
    hours_est_dev = fields.Float(string='Hours Est Dev')
    hours_overflowed = fields.Float(string='Hours Overflowed')
    hours_spent_dev = fields.Float(string='Hours Spent Dev')
    hours_spent_pm = fields.Float(string='Hours Spent PM')
    hours_spent_qa = fields.Float(string='Hours Spent QA')
    stories = fields.Float(string='Stories')
    status = fields.Selection([
        ('discovery', 'Discovery'),
        ('development', 'Development'),
        ('sandbox_review', 'Sandbox Review'),
        ('regression_testing', 'Regression Testing'),
        ('deployment', 'Deployment'),
        ('data_upload', 'Data Upload'),
        ('user_acceptance', 'User Acceptance'),
        ('training', 'Training'),
        ('support', 'Support'),
        ('amc', 'AMC'),
        ('closed', 'Closed'),
        ('hold', 'Hold'),
    ], string='Status')
    sync_wc = fields.Boolean(string='Sync WC')
    wc_id = fields.Char(string='Wc Id')

    timesheet_count = fields.Float(
        string="Timesheet Hours",
        compute='_compute_timesheet_count'
    )

    def _compute_timesheet_count(self):
        for project in self:
            lines = self.env['account.analytic.line'].search([('project_id', '=', project.id)])
            project.timesheet_count = sum(lines.mapped('unit_amount'))

    # ------------------------------------------------------------------
    # On-Time Delivery (all-time; the dashboard shows the same figures per
    # period). The maths lives on project.task so the two can never drift.
    # ------------------------------------------------------------------
    ft_on_time_rate = fields.Float(
        string='On-Time Delivery (%)',
        compute='_compute_ft_delivery_stats',
        store=False,
        readonly=True,
        # Not 'group_operator' — deprecated in Odoo 18. Averaging a ratio across
        # projects would be wrong anyway (a 1-task project would weigh the same
        # as a 500-task one), so no aggregate is offered.
        aggregator=False,
        help="Share of delivered tasks that met their deadline, all-time. "
             "Target: 95% or above. Tasks delivered without a deadline are not "
             "counted either way — see Delivered Without Deadline. Reads 0 when "
             "nothing measurable has been delivered yet.",
    )
    ft_delivered_tasks = fields.Integer(
        string='Delivered Tasks',
        compute='_compute_ft_delivery_stats',
        store=False,
        readonly=True,
        help="Tasks that reached a Completed (folded) stage. Excludes cancelled.",
    )
    ft_on_time_tasks = fields.Integer(
        string='Delivered On Time',
        compute='_compute_ft_delivery_stats',
        store=False,
        readonly=True,
        help="Delivered tasks whose completion date was on or before the deadline.",
    )
    ft_late_tasks = fields.Integer(
        string='Delivered Late',
        compute='_compute_ft_delivery_stats',
        store=False,
        readonly=True,
        help="Delivered tasks whose completion date was after the deadline.",
    )
    ft_no_deadline_tasks = fields.Integer(
        string='Delivered Without Deadline',
        compute='_compute_ft_delivery_stats',
        store=False,
        readonly=True,
        help="Delivered tasks that had no deadline set, so they could not be "
             "judged on time. The On-Time Delivery percentage ignores these; a "
             "large number here means the percentage covers only a small slice "
             "of the work.",
    )
    ft_overdue_open_tasks = fields.Integer(
        string='Open & Overdue',
        compute='_compute_ft_delivery_stats',
        store=False,
        readonly=True,
        help="Tasks still open whose deadline has already passed. Read this "
             "alongside On-Time Delivery: the percentage only counts work that "
             "finished, so late work that never finishes is invisible to it.",
    )

    ft_efficiency_rate = fields.Float(
        string='Delivery Efficiency (%)',
        compute='_compute_ft_delivery_stats',
        store=False,
        readonly=True,
        aggregator=False,
        help="Estimated hours divided by actual hours across delivered tasks, "
             "as a percentage. Target: 90-110%. Below 90% the work is taking "
             "longer than estimated; above 110% the estimates are padded. Only "
             "tasks that have BOTH an estimate and logged time are counted — see "
             "Tasks Without an Estimate.",
    )
    ft_estimated_hours = fields.Float(
        string='Estimated Hours (Delivered)',
        compute='_compute_ft_delivery_stats',
        store=False,
        readonly=True,
        help="Allocated hours on delivered tasks that also have logged time. "
             "The numerator of Delivery Efficiency.",
    )
    ft_actual_hours = fields.Float(
        string='Actual Hours (Delivered)',
        compute='_compute_ft_delivery_stats',
        store=False,
        readonly=True,
        help="Timesheeted hours on the same tasks. The denominator of Delivery "
             "Efficiency.",
    )
    ft_unestimated_tasks = fields.Integer(
        string='Tasks Without an Estimate',
        compute='_compute_ft_delivery_stats',
        store=False,
        readonly=True,
        help="Delivered tasks left out of Delivery Efficiency because they had "
             "no estimate or no logged time. A large number here means the "
             "percentage covers only a small slice of the work.",
    )
    ft_rework_rate = fields.Float(
        string='Rework Rate (%)',
        compute='_compute_ft_delivery_stats',
        store=False,
        readonly=True,
        aggregator=False,
        help="Share of delivered tasks that were reopened at least once. "
             "Target: 10% or below. Counts tasks, not reopen events, so one task "
             "bounced repeatedly cannot push the rate past 100%. Only reopens "
             "since this feature was installed are counted.",
    )
    ft_reworked_tasks = fields.Integer(
        string='Reworked Tasks',
        compute='_compute_ft_delivery_stats',
        store=False,
        readonly=True,
        help="Delivered tasks that were sent back for rework at least once.",
    )
    ft_rework_hours = fields.Float(
        string='Rework Hours',
        compute='_compute_ft_delivery_stats',
        store=False,
        readonly=True,
        help="Time logged on delivered tasks after they were sent back for "
             "rework — the cost of the additional correction round.",
    )
    ft_rework_hours_rate = fields.Float(
        string='Rework Hours (%)',
        compute='_compute_ft_delivery_stats',
        store=False,
        readonly=True,
        aggregator=False,
        help="Share of the effort on delivered tasks that went into rework. "
             "Answers a different question from Rework Rate beside it: that one "
             "counts how OFTEN work comes back, this one how much it COSTS. One "
             "task reopened once can be 2% of the count and half the hours.",
    )

    @api.depends('tasks.estimated')
    def _compute_estimated(self):
        for project in self:
            project.estimated = round(sum(project.tasks.mapped('estimated')), 2)

    # stage_id.name joins the depends for the same reason it is in
    # _compute_ft_completion_date's: whether a stage counts as delivered now
    # turns on its name as well as its fold flag.
    @api.depends('task_ids.ft_completion_date', 'task_ids.date_deadline',
                 'task_ids.stage_id.fold', 'task_ids.stage_id.name',
                 'task_ids.state',
                 'task_ids.estimated', 'task_ids.effective_hours',
                 'task_ids.ft_reopen_count', 'task_ids.ft_rework_hours')
    def _compute_ft_delivery_stats(self):
        Task = self.env['project.task']
        # Two queries for the whole set rather than two per project — this
        # compute runs for every row of the project list view.
        stats_by_project = Task._ft_on_time_stats_by_project(self.ids)
        overdue_by_project = Task._ft_overdue_open_count_by_project(self.ids)
        for project in self:
            stats = stats_by_project.get(project.id) or {}
            project.ft_delivered_tasks = stats.get('completed', 0)
            project.ft_on_time_tasks = stats.get('on_time', 0)
            project.ft_late_tasks = stats.get('late', 0)
            project.ft_no_deadline_tasks = stats.get('no_deadline', 0)
            # A Float cannot hold "no data", so an unmeasurable project reads 0.
            # ft_delivered_tasks / ft_no_deadline_tasks are what tell them apart.
            project.ft_on_time_rate = stats.get('rate') or 0.0
            project.ft_overdue_open_tasks = overdue_by_project.get(project.id, 0)
            # Same "a Float cannot hold no-data" caveat as the on-time rate:
            # ft_unestimated_tasks / ft_delivered_tasks tell 0% apart from
            # nothing-to-measure.
            project.ft_efficiency_rate = stats.get('efficiency_rate') or 0.0
            project.ft_estimated_hours = stats.get('estimated_hours', 0.0)
            project.ft_actual_hours = stats.get('actual_hours', 0.0)
            project.ft_unestimated_tasks = stats.get('unestimated', 0)
            project.ft_rework_rate = stats.get('rework_rate') or 0.0
            project.ft_reworked_tasks = stats.get('reworked', 0)
            project.ft_rework_hours = stats.get('rework_hours', 0.0)
            project.ft_rework_hours_rate = stats.get('rework_hours_rate') or 0.0

    @api.model_create_multi
    def create(self, vals_list):
        # #3 - Only Administrators may create projects.
        if not self.env.su and not self.env.user.has_group('base.group_system'):
            raise UserError(_("Only an Administrator can create projects."))
        # ft_project_type carries no default so that nothing is pre-filled in
        # the UI (see the field definition). Superuser creates have no form to
        # fill it in — module install, migrations, hr_timesheet's per-company
        # "Internal" project and sale_timesheet's project-from-sale-order all
        # arrive here sudo'd — so they get the historical value rather than a
        # required-field error. Everything a person creates goes through a form
        # that now asks for it.
        if self.env.su:
            for vals in vals_list:
                vals.setdefault('ft_project_type', self.FT_FALLBACK_PROJECT_TYPE)
        return super().create(vals_list)

    def write(self, vals):
        # #4 - Only a Project Manager (by job position) or an Administrator
        # may change the project status/stage (the status bar = stage_id).
        if ('status' in vals or 'stage_id' in vals) and not self.env.su:
            user = self.env.user
            job = (
                (user.employee_id.sudo().job_id.name or '').strip().lower()
                if user.employee_id else ''
            )
            if job not in PM_JOB_NAMES and not user.has_group('base.group_system'):
                raise UserError(_("Only a Project Manager can change the project status."))
        # Stage Validation Framework (task points 1-10): a move into a stage is
        # blocked unless that stage's required milestone date is present. Only on
        # stage_id — the Kanban status bar — never on task stages, and never on
        # `status` (the legacy selection). Skipped under sudo so migrations and
        # server actions are not tripped by data that predates the rule.
        if 'stage_id' in vals and vals['stage_id'] and not self.env.su:
            target_stage = self.env['project.project.stage'].browse(vals['stage_id']).exists()
            if target_stage:
                self._ft_check_stage_entry_dates(target_stage, vals)
        if 'timesheet_ids' in vals:
            deduped = []
            for cmd in vals['timesheet_ids']:
                # cmd[0] == 0 means "create new record via O2M"
                if cmd[0] == 0:
                    cv = cmd[2] or {}
                    task_id = cv.get('task_id')
                    # Only deduplicate when the record came from a task save
                    # (task timesheets always carry a task_id)
                    if task_id:
                        domain = [
                            ('task_id', '=', task_id),
                            ('project_id', 'in', self.ids),
                        ]
                        # Add optional fields only when present in the command
                        # vals to avoid False-vs-'' mismatches causing missed hits
                        if cv.get('date'):
                            domain.append(('date', '=', cv['date']))
                        if cv.get('employee_id'):
                            domain.append(('employee_id', '=', cv['employee_id']))
                        if cv.get('unit_amount') is not None:
                            domain.append(('unit_amount', '=', cv['unit_amount']))
                        existing = self.env['account.analytic.line'].search(
                            domain, limit=1
                        )
                        if existing:
                            # Replace create with a plain link to the existing record
                            deduped.append((4, existing.id, 0))
                            continue
                deduped.append(cmd)
            vals['timesheet_ids'] = deduped
        return super().write(vals)

    def action_view_timesheets(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('hr_timesheet.timesheet_action_all')
        action['domain'] = [('project_id', '=', self.id)]
        action['context'] = {
            'default_project_id': self.id,
            'search_default_project_id': self.id,
            'group_by': [ 'jobposition_id', 'employee_id','task_id'],
        }
        return action


class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    jobposition_id = fields.Many2one(
        'hr.job',
        string="Job Position",
        readonly=False,
    )
    module_id = fields.Many2one('cus.module',related='task_id.module_id',string='Module')
    project_status = fields.Many2one(
        'project.project.stage',
        string='Project Stage', store=True, readonly=True,
        help='Snapshot of the project stage at the time the timesheet was created. '
             'Frozen after creation and only updates if the project itself is changed.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        result_ids = []
        to_create = []
        for vals in vals_list:
            task_id = vals.get('task_id')
            project_id = vals.get('project_id')
            # When both task_id and project_id are present, the project form's
            # O2M widget can re-submit a task timesheet as a create command even
            # though the record already exists in the DB.  Detect and skip it.
            if task_id and project_id:
                domain = [
                    ('task_id', '=', task_id),
                    ('project_id', '=', project_id),
                ]
                if vals.get('date'):
                    domain.append(('date', '=', vals['date']))
                if vals.get('employee_id'):
                    domain.append(('employee_id', '=', vals['employee_id']))
                if vals.get('unit_amount') is not None:
                    domain.append(('unit_amount', '=', vals['unit_amount']))
                existing = self.search(domain, limit=1)
                if existing:
                    result_ids.append(existing.id)
                    continue
            if project_id and not vals.get('project_status'):
                project = self.env['project.project'].browse(project_id)
                if project.stage_id:
                    vals['project_status'] = project.stage_id.id
            to_create.append(vals)
        created = super().create(to_create) if to_create else self.browse()
        return self.browse(result_ids) | created

    def write(self, vals):
        # Only refresh project_status snapshot when the project itself changes
        if 'project_id' in vals:
            project = self.env['project.project'].browse(vals['project_id']) if vals['project_id'] else False
            vals['project_status'] = project.stage_id.id if project and project.stage_id else False
        return super().write(vals)

    @api.constrains('project_id', 'unit_amount')
    def _check_project_status_open(self):
        # #1 - No time entries when the project is Closed or On Hold. The PMS
        # tracks this via the project STAGE (stage_id, the status bar) and also
        # the custom `status` selection, so block on either.
        blocked_stage_names = ('closed', 'hold', 'on hold')
        for line in self:
            project = line.project_id
            if not project:
                continue
            stage_name = (project.stage_id.name or '').strip().lower()
            status_blocked = project.status in ('closed', 'hold')
            if stage_name in blocked_stage_names or status_blocked:
                label = project.stage_id.name if stage_name in blocked_stage_names \
                    else dict(project._fields['status'].selection).get(project.status, project.status)
                raise ValidationError(_(
                    "You cannot log time on project '%s' because it is %s."
                ) % (project.name, label))
    used_ai = fields.Boolean(string='Used AI')
    chat_link = fields.Char(string='Chat Link')
    reason = fields.Char(string='Reason')
    hours_saved = fields.Float(string='Hours Saved')
    challenges = fields.Text(string='Challenges')
    ai_time_impact = fields.Selection([
        ('0', '0'),
        ('15_mins', '15 mins'),
        ('30_mins', '30 mins'),
        ('1_hour', '1 hour'),
        ('2_hours', '2 hours'),
        ('3_hours', '3 hours'),
        ('5_hours', '5 hours'),
        ('8_plus_hours', '8+ hours'),
        ('more_time', 'More time taken'),
        ('na', 'N/A'),
    ], string='AI Time Impact')


    # @api.depends('employee_id.job_id')
    # def _compute_jobposition_id(self):
    #     """
    #     Compute: Sync from Employee -> Timesheet
    #     When the employee's job_id changes, update the timesheet jobposition_id.
    #     """
    #     for line in self:
    #         if line.employee_id and line._get_job_update_needed():
    #             line.jobposition_id = line.employee_id.job_id
    #         else:
    #             # Clear if no employee
    #             line.jobposition_id = False
    #
    # def _inverse_jobposition_id(self):
    #     """
    #     Inverse: Sync from Timesheet -> Employee
    #     When jobposition_id changes on the timesheet, update the employee's job_id.
    #     """
    #     for line in self:
    #         if line.employee_id and line._get_job_update_needed():
    #             line.employee_id.job_id = line.jobposition_id or False
    #
    # def _get_job_update_needed(self):
    #     """
    #     Helper method to check whether the timesheet job position
    #     and the employee's job position are different.
    #     This prevents infinite loops and unnecessary writes.
    #     """
    #     self.ensure_one()
    #     return self.employee_id and self.jobposition_id != self.employee_id.job_id
