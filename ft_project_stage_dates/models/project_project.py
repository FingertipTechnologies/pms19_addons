from odoo import api, fields, models, _
from odoo.exceptions import UserError

# Groups that decide who may edit the PLANNED lifecycle dates directly.
APPROVER_GROUP = 'project_date_extension.group_project_date_extension_approver'
TECHNICAL_ARCHITECT_GROUP = 'ft_project_stage_dates.group_technical_architect'

# Stage keys (project.project.stage._ft_stage_key) during which a Technical
# Architect may still edit the planned dates directly. From DEV onwards the
# plan is a commitment and changes go through a Date Extension Request.
EARLY_STAGE_KEYS = ('kickoff', 'disc')

# The Implementation lifecycle, in pipeline order, by stage key. CLOSED is the
# shared terminal stage every type may reach; it is listed because an
# Implementation project's closing date is part of its timeline.
PL_ACTUAL_STAGE_KEYS = (
    'kickoff', 'disc', 'dev', 'reg', 'srv', 'uat', 'data', 'tra', 'support',
    'closed',
)

# stage key -> the stored Date field holding the date the project first
# ENTERED that stage. Public: ft_project_stage_report (and anything else
# reading the actual timeline) imports this rather than re-deriving the names.
PL_ACTUAL_DATE_FIELDS = {
    key: 'pl_actual_%s_date' % key for key in PL_ACTUAL_STAGE_KEYS
}

# Context key under which the automatic stamping (and the install backfill)
# writes the actual dates. Together with superuser it is the only way past the
# read-only guard in write()/create().
STAMPING_CONTEXT_KEY = 'pl_stamping_actual_dates'


class ProjectProject(models.Model):
    _inherit = 'project.project'

    # ------------------------------------------------------------------
    # Actual stage-entry dates (system-generated, read-only)
    # ------------------------------------------------------------------
    # One Date per Implementation stage: the day the project FIRST entered it.
    # Stamped by _pl_stamp_actual_stage_dates on create and on every stage
    # change, only when still empty, so moving a project back and forward
    # keeps the first entry (the chatter holds every later move). readonly in
    # the form, and refused on any direct write that is not the stamping
    # itself or superuser (see _pl_guard_actual_date_vals). copy=False: a
    # duplicated project has not entered anything yet. tracking=False: the
    # stage_id tracking already tells the same story in the chatter.
    pl_actual_kickoff_date = fields.Date(
        string='KICKOFF Entered On', readonly=True, copy=False,
        help='Date the project first entered KICKOFF. Recorded automatically.')
    pl_actual_disc_date = fields.Date(
        string='DISC Entered On', readonly=True, copy=False,
        help='Date the project first entered DISC. Recorded automatically.')
    pl_actual_dev_date = fields.Date(
        string='DEV Entered On', readonly=True, copy=False,
        help='Date the project first entered DEV. Recorded automatically.')
    pl_actual_reg_date = fields.Date(
        string='REG Entered On', readonly=True, copy=False,
        help='Date the project first entered REG. Recorded automatically.')
    pl_actual_srv_date = fields.Date(
        string='SRV Entered On', readonly=True, copy=False,
        help='Date the project first entered SRV. Recorded automatically.')
    pl_actual_uat_date = fields.Date(
        string='UAT Entered On', readonly=True, copy=False,
        help='Date the project first entered UAT. Recorded automatically.')
    pl_actual_data_date = fields.Date(
        string='DATA Entered On', readonly=True, copy=False,
        help='Date the project first entered DATA. Recorded automatically.')
    pl_actual_tra_date = fields.Date(
        string='TRA Entered On', readonly=True, copy=False,
        help='Date the project first entered TRA. Recorded automatically.')
    pl_actual_support_date = fields.Date(
        string='SUPPORT Entered On', readonly=True, copy=False,
        help='Date the project first entered SUPPORT. Recorded automatically.')
    pl_actual_closed_date = fields.Date(
        string='CLOSED Entered On', readonly=True, copy=False,
        help='Date the project first entered CLOSED. Recorded automatically. '
             'The planned Closed Date (core End Date) is a separate field and '
             'keeps its own stamping on CLOSED.')

    # ------------------------------------------------------------------
    # Public helpers (used by the stage report)
    # ------------------------------------------------------------------
    @api.model
    def _pl_actual_date_field(self, key):
        """Technical name of the actual-entry Date field for stage ``key``
        ('kickoff', 'disc', ... 'closed'), or False for a key that has none
        ('hold', 'amc', an unclassified stage)."""
        return PL_ACTUAL_DATE_FIELDS.get(key, False)

    def _pl_actual_entry_dates(self):
        """The project's actual timeline: ``[(key, stage, date), ...]``.

        One entry per Implementation stage (every stage flagged
        pl_for_implementation, CLOSED included) in pipeline order, with the
        stage record and the date the project first entered it (False while
        it has not). A stage whose name does not classify to a lifecycle key,
        or whose key has no actual-date field, is skipped; when two live
        stages share a key the earliest in the pipeline represents it.
        """
        self.ensure_one()
        result = []
        seen = set()
        for stage in self._pl_allowed_stages_for_type('implementation'):
            key = stage._ft_stage_key()
            fname = PL_ACTUAL_DATE_FIELDS.get(key)
            if not fname or key in seen:
                continue
            seen.add(key)
            result.append((key, stage, self[fname]))
        return result

    def _pl_in_early_stage(self):
        """True for an Implementation project still in KICKOFF or DISC."""
        self.ensure_one()
        return (
            self.ft_project_type == 'implementation'
            and bool(self.stage_id)
            and self.stage_id._ft_stage_key() in EARLY_STAGE_KEYS
        )

    # ------------------------------------------------------------------
    # Stamping
    # ------------------------------------------------------------------
    def _pl_stamp_actual_stage_dates(self):
        """Stamp today on the actual-entry date of each project's CURRENT
        stage, Implementation projects only, and only when that date is still
        empty: the first entry wins and a project moved back and forward keeps
        it. Written under sudo and the stamping context so the read-only guard
        lets it through and no permission rule on the user applies."""
        today = fields.Date.context_today(self)
        for project in self:
            if project.ft_project_type != 'implementation' or not project.stage_id:
                continue
            fname = PL_ACTUAL_DATE_FIELDS.get(project.stage_id._ft_stage_key())
            if not fname or project[fname]:
                continue
            # super(...) rather than project.write: nothing above this class
            # in the MRO needs to see the stamp, and the write never carries
            # stage_id, so there is no re-entry into the stamping either way.
            super(ProjectProject, project.sudo().with_context(
                **{STAMPING_CONTEXT_KEY: True})).write({fname: today})

    def _pl_guard_actual_date_vals(self, vals):
        """Refuse a direct write of an actual-entry date. Only the stamping
        itself (context) and superuser (install backfill, migrations) pass."""
        if self.env.su or self.env.context.get(STAMPING_CONTEXT_KEY):
            return
        if any(fname in vals for fname in PL_ACTUAL_DATE_FIELDS.values()):
            raise UserError(_(
                "Actual stage dates are recorded automatically when a project "
                "enters a stage and cannot be edited."))

    def _pl_stamp_lifecycle_dates(self):
        """ft_project_lifecycle stamps the planned Closed Date (core ``date``)
        on entering CLOSED and the Hold Date from the On Hold flag, writing
        them as the current user. Closed Date is now one of the protected,
        sequenced lifecycle dates, so that write would be refused for every
        Project Manager who is not a Date Extension Approver and checked
        against the planned Support End Date it may well precede. The stamp is
        a system action, not a user edit: run it under sudo (uid unchanged, so
        the chatter still names the mover) and without the sequence check,
        which is what the milestone Kick-off sync already does."""
        return super(ProjectProject, self.sudo().with_context(
            skip_date_sequence_check=True))._pl_stamp_lifecycle_dates()

    # ------------------------------------------------------------------
    # project_date_extension: who may edit the planned dates, and which
    # ------------------------------------------------------------------
    def _sequenced_date_fields(self):
        """project_date_extension matches its twelve lifecycle steps by field
        LABEL. Two never matched: Kick-off Date is the field
        kick_start_meeting_date, whose label is "Kick Start Meeting Date" (the
        form relabels it), and Closed Date is core ``date``, labelled
        "Expiration Date". Both were therefore neither protected nor held to
        the step order. Put them in by technical name at their steps: Kick-off
        is step 2 (after Start Date) and Closed is step 12 (last)."""
        by_label = {}
        for name, label in super()._sequenced_date_fields():
            by_label.setdefault(label, name)
        overrides = {
            'Kick-off Date': 'kick_start_meeting_date',
            'Closed Date': 'date',
        }
        result = []
        for label in self._SEQUENCED_DATE_LABELS:
            name = by_label.get(label)
            if not name and overrides.get(label) in self._fields:
                name = overrides[label]
            if name:
                result.append((name, label))
        return result

    def _check_date_edit_permission(self, vals):
        """Technical Architects may edit the planned lifecycle dates directly
        while EVERY project in self is an Implementation project in an early
        stage (KICKOFF or DISC). On create (self empty) they are allowed too.
        Superuser and the Date Extension Approver keep their rights; everybody
        else falls through to project_date_extension's check, which refuses
        the edit and points at the Date Extension Request flow.

        The stage read is the CURRENT one: a write that moves the project out
        of DISC and changes a date in the same call is judged on DISC."""
        if self.env.su:
            return
        user = self.env.user
        if user.has_group(APPROVER_GROUP):
            return
        if user.has_group(TECHNICAL_ARCHITECT_GROUP) and all(
                project._pl_in_early_stage() for project in self):
            return
        return super()._check_date_edit_permission(vals)

    # ------------------------------------------------------------------
    # Form: ft_can_edit_project_dates mirrors the server rule
    # ------------------------------------------------------------------
    # Redeclared only to add depends_context=('uid',): the value is a
    # property of the USER (group membership), but ft_task_hours_tracker
    # declares it without a context dependency, so the ORM shares one cached
    # value between environments - a value computed for one user was handed
    # back to the next with_user() in the same transaction.
    ft_can_edit_project_dates = fields.Boolean(
        compute='_compute_ft_can_edit_project_dates',
        depends_context=('uid',),
    )

    @api.depends('stage_id', 'ft_project_type')
    def _compute_ft_can_edit_project_dates(self):
        """Administrators keep the form editable as before (base.group_system
        does not imply the approver group, so the server may still refuse
        them, exactly as today); Date Extension Approvers always; Technical
        Architects on an early-stage Implementation project and on a record
        not yet saved; nobody else."""
        user = self.env.user
        if user.has_group('base.group_system') or user.has_group(APPROVER_GROUP):
            for project in self:
                project.ft_can_edit_project_dates = True
            return
        is_architect = user.has_group(TECHNICAL_ARCHITECT_GROUP)
        for project in self:
            project.ft_can_edit_project_dates = is_architect and (
                not project.id or project._pl_in_early_stage())

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._pl_guard_actual_date_vals(vals)
        projects = super().create(vals_list)
        # After ft_project_lifecycle has homed each project on its type's
        # first stage (KICKOFF for Implementation).
        projects._pl_stamp_actual_stage_dates()
        return projects

    def write(self, vals):
        self._pl_guard_actual_date_vals(vals)
        res = super().write(vals)
        # A type change re-homes the project (ft_project_lifecycle) through a
        # nested write that does carry stage_id; the check on ft_project_type
        # covers the one case it does not - a project already on the shared
        # CLOSED stage becoming Implementation.
        if 'stage_id' in vals or 'ft_project_type' in vals:
            self._pl_stamp_actual_stage_dates()
        return res
