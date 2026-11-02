# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from datetime import timedelta

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

APPROVER_GROUP = "project_date_extension.group_project_date_extension_approver"

# Stage -> the project date by which the project must have REACHED that stage,
# i.e. the stage's own planned (start) date. Extending that date is extending
# the stage. Keyed by the upper-cased stage name (project.project.stage.name)
# so this module needs no dependency on the module that defines the stages;
# the value is the technical name of the Date field on project.project (the
# same names project.lifecycle.date rows carry).
#
# Deliberately NOT the next stage's date ("planned end of the stage"), which
# is how this map was first written: that paired DEV with the Regression Date,
# REG with the Sandbox Review Date and so on, so the Date Extension Request
# screen showed REG's date under "DEV". On the project form the dates are
# named after the stage they belong to (Regression Date is REG's date), and
# bt_project_customization's Overdue flag (FT_OVERDUE_MILESTONES, extended by
# ft_project_lifecycle._ft_overdue_milestones for DATA) already reads them
# that way. This map mirrors FT_OVERDUE_MILESTONES key for key - plus KICKOFF
# (Start Date) and CLOSED (Closed Date), which are no milestone - so there is
# ONE set of dates with ONE meaning: the form, the Overdue flag, the extension
# screen and the stage report all agree. A test in this module keeps the two
# maps from drifting apart. Go Live Date (seq 85) and Support End Date (seq
# 100) are nobody's stage date any more; they stay reachable through the
# legacy hand-picked Date to Extend.
#
# Public: other modules (stage-wise delay report) import this constant and the
# ``_stage_planned_date_field`` helper below. Keep the names stable.
STAGE_PLANNED_DATE_FIELD = {
    "KICKOFF": "date_start",               # Start Date
    "DISC": "kick_start_meeting_date",     # Kick-off Date
    "DEV": "brd_approval_date",            # BRD Approval Date
    "REG": "ft_regression_date",           # Regression Date
    "SRV": "sandbox_review_date",          # Sandbox Review Date
    "UAT": "uat_start_date",               # UAT Start Date
    "DATA": "pl_data_upload_date",         # Data Upload Date
    "TRA": "ft_training_date",             # Training Date
    "SUPPORT": "support_start_date",       # Support Start Date
    "CLOSED": "date",                      # Closed Date
}


def _stage_key(stage):
    """Normalised dictionary key for a project.project.stage record (or a
    plain name): upper-cased, stripped."""
    name = stage if isinstance(stage, str) else (stage.name if stage else "")
    return (name or "").strip().upper()


def _stage_planned_date_field(stage):
    """Technical name of the project.project Date field by which the project
    must have reached ``stage`` (a project.project.stage record or its name)
    - the stage's planned start, not its end - or None when the stage has no
    planned date (AMC/General stages, unknown names). Public helper, see
    STAGE_PLANNED_DATE_FIELD."""
    return STAGE_PLANNED_DATE_FIELD.get(_stage_key(stage))


class ProjectDateExtensionRequest(models.Model):
    """Point 1 & 2: A Date Extension Request linked to a Project and one of
    its milestones, capturing project, milestone, current date, requested
    new date, reason, requester and status.
    """

    _name = "project.date.extension.request"
    _description = "Project Date Extension Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    name = fields.Char(
        string="Reference",
        default=lambda self: _("New"),
        copy=False,
        readonly=True,
    )

    # --- Point 2: extension details -------------------------------------
    project_id = fields.Many2one(
        "project.project",
        string="Project",
        required=True,
        tracking=True,
        ondelete="cascade",
        index=True,
    )
    milestone_id = fields.Many2one(
        "project.custom.milestone",
        string="Milestone",
        tracking=True,
        ondelete="restrict",
        domain="[('project_id', '=', project_id)]",
        help="Kept for backward compatibility; extensions now target a "
        "project lifecycle date.",
    )
    stage_id = fields.Many2one(
        "project.project.stage",
        string="Current Stage",
        compute="_compute_current_stage",
        store=True,
        readonly=False,
        tracking=True,
        help="The project's current stage (read-only). It decides which "
        "dates are offered for extension.",
    )
    stage_to_extend_id = fields.Many2one(
        "project.project.stage",
        string="Stage to be Extended",
        tracking=True,
        ondelete="restrict",
        domain="[('id', 'in', allowed_stage_ids)]",
        help="The project stage whose planned date - the date by which the "
        "project must have reached it, as named on the project form (REG: "
        "Regression Date, UAT: UAT Start Date, ...) - is being rescheduled. "
        "Only the project's current stage and the stages after it are "
        "offered. Choosing a stage selects its planned date automatically.",
    )
    allowed_stage_ids = fields.Many2many(
        "project.project.stage",
        compute="_compute_allowed_stage_ids",
        string="Allowed Stages",
    )
    date_to_extend_id = fields.Many2one(
        "project.lifecycle.date",
        string="Date to Extend",
        compute="_compute_date_to_extend_id",
        store=True,
        readonly=False,
        tracking=True,
        ondelete="restrict",
        domain="[('id', 'in', allowed_date_ids)]",
        help="The project date this request moves. Set automatically from "
        "the Stage to be Extended (the date that stage must be reached by), "
        "or picked by hand with the stage left empty: for projects with no "
        "applicable stage (AMC / General) and for the Go Live and Support "
        "End dates, which belong to no stage. Only the current stage's date "
        "and the dates after it are offered; earlier dates have already "
        "passed.",
    )
    allowed_date_ids = fields.Many2many(
        "project.lifecycle.date",
        compute="_compute_allowed_date_ids",
        string="Allowed Dates",
    )
    current_date = fields.Date(
        string="Current Date",
        compute="_compute_current_date",
        store=True,
        readonly=True,
        copy=False,
        help="Planned date of the selected stage (the date the project must "
        "reach it by) as it stood when the stage was chosen. Refreshed from "
        "the project at approval time, so the "
        "history shows the date that was actually moved. It is NOT "
        "recomputed when the project date changes in between.",
    )
    requested_date = fields.Date(
        string="Rescheduled Date",
        required=True,
        tracking=True,
        help="The new planned date for the selected stage.",
    )
    extension_days = fields.Integer(
        string="Extension Days",
        compute="_compute_extension_days",
        store=True,
        help="Rescheduled Date minus Current Date, in days. Positive for an "
        "extension (delay), negative for a preponement.",
    )
    is_preponement = fields.Boolean(
        string="Preponement",
        compute="_compute_extension_days",
        store=True,
        help="The Rescheduled Date is EARLIER than the Current Date. A "
        "preponement moves only the selected date; later dates are never "
        "shifted backwards and it never counts as a delay.",
    )
    delay_days = fields.Integer(
        string="Delay Days",
        compute="_compute_extension_days",
        store=True,
        help="The delay this request adds: Extension Days when positive, "
        "otherwise 0 (a preponement is never a delay). Reports sum this "
        "field over approved requests.",
    )
    downstream_impact = fields.Html(
        string="Impact on later dates",
        compute="_compute_downstream_impact",
        sanitize=False,
        help="Preview of the later planned dates that approval will move, "
        "and to what.",
    )
    downstream_impact_applied = fields.Html(
        string="Impact applied at approval", readonly=True, copy=False,
        sanitize=False,
        help="The later dates as they were shifted when the request was "
        "approved (audit trail); shown instead of the live preview once "
        "approved.",
    )
    reason = fields.Text(string="Reason", required=True)
    requester_id = fields.Many2one(
        "res.users",
        string="Requested By",
        default=lambda self: self.env.user,
        tracking=True,
        help="The user this extension is for. An admin can create the "
        "request on a user's behalf and assign them here; that user then "
        "submits it for approval.",
    )
    is_approver = fields.Boolean(
        compute="_compute_is_approver",
        help="Technical: whether the current user may approve/reject and "
        "assign the requester.",
    )
    can_submit = fields.Boolean(
        compute="_compute_can_submit",
        help="Technical: whether the current user may submit this draft "
        "(the assigned requester or an admin).",
    )

    def _compute_is_approver(self):
        is_appr = self.env.user.has_group(APPROVER_GROUP)
        for rec in self:
            rec.is_approver = is_appr

    def _compute_can_submit(self):
        is_appr = self.env.user.has_group(APPROVER_GROUP)
        for rec in self:
            rec.can_submit = rec.state == "draft" and (
                is_appr or self.env.user == rec.requester_id
            )

    # --- Point 3: Request/Draft -> Approved / Rejected workflow ---------
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("request", "Request"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        string="Status",
        default="draft",
        copy=False,
        tracking=True,
        index=True,
    )

    # --- Point 4 & 7: approval / history ---------------------------------
    approver_id = fields.Many2one(
        "res.users",
        string="Approved/Rejected By",
        readonly=True,
        copy=False,
        tracking=True,
    )
    decision_date = fields.Datetime(
        string="Decision Date",
        readonly=True,
        copy=False,
    )
    rejection_reason = fields.Text(string="Rejection Reason", copy=False, tracking=True)
    approval_comment = fields.Text(string="Approval Comment", copy=False, tracking=True)

    company_id = fields.Many2one(
        related="project_id.company_id", store=True, readonly=True
    )

    # ----------------------------------------------------------------
    # Onchange / create
    # ----------------------------------------------------------------
    # Where each stage sits in the lifecycle: the sequence of the first
    # date to offer when the project is in that stage. Dates before it have
    # already passed, so they are hidden. The first date offered is the
    # stage's OWN date - the one the project must have reached the stage by
    # - which is exactly the STAGE_PLANNED_DATE_FIELD pairing (DEV: BRD
    # Approval, seq 30; SUPPORT: Support Start, seq 90), so the legacy date
    # picker and the stage dropdown start from the same date. Unknown
    # stages fall back to showing everything.
    _STAGE_MIN_SEQUENCE = {
        "KICKOFF": 10,    # Start Date onward
        "DISC": 20,       # Kick-off Date onward
        "DEV": 30,        # BRD Approval Date onward
        "REG": 40,        # Regression Date onward
        "SRV": 50,        # Sandbox Review Date onward
        "UAT": 60,        # UAT Start Date onward
        "DATA": 70,       # Data Upload Date onward
        "TRA": 80,        # Training Date onward
        "SUPPORT": 90,    # Support Start / Support End / Closed
        "HOLD": 10,       # paused - show everything
        "CLOSED": 110,    # Closed Date only
    }

    def _current_min_sequence(self):
        self.ensure_one()
        stage = self.stage_id
        return self._STAGE_MIN_SEQUENCE.get(_stage_key(stage), 10) if stage else 10

    @api.depends("project_id", "stage_id")
    def _compute_allowed_date_ids(self):
        Dates = self.env["project.lifecycle.date"]
        project_fields = self.env["project.project"]._fields
        for rec in self:
            min_seq = rec._current_min_sequence()
            rec.allowed_date_ids = Dates.search(
                [("sequence", ">=", min_seq)]
            ).filtered(lambda d: d.field_name in project_fields)

    @api.depends("project_id")
    def _compute_current_stage(self):
        for rec in self:
            project = rec.project_id
            rec.stage_id = (
                project.stage_id
                if project and "stage_id" in project._fields
                else False
            )

    # ----------------------------------------------------------------
    # Stage to be Extended -> planned date
    # ----------------------------------------------------------------
    # Project type -> the flag on project.project.stage that marks a stage as
    # part of that type's lifecycle (fields added by ft_project_lifecycle;
    # guarded, this module does not depend on it).
    _PROJECT_TYPE_STAGE_FLAG = {
        "implementation": "pl_for_implementation",
        "amc": "pl_for_amc",
        "general": "pl_for_general",
    }

    @api.model
    def _stage_lifecycle_date(self, stage):
        """The project.lifecycle.date row of the date ``stage`` must be
        reached by (its planned start, see STAGE_PLANNED_DATE_FIELD); empty
        recordset when the stage has none or the row/field does not exist."""
        Dates = self.env["project.lifecycle.date"]
        fname = _stage_planned_date_field(stage)
        if not fname or fname not in self.env["project.project"]._fields:
            return Dates
        return Dates.search([("field_name", "=", fname)], limit=1)

    @api.depends("project_id", "stage_id")
    def _compute_allowed_stage_ids(self):
        """Stages a request may target: those of the project's type (when
        the pl_for_* flags exist), from the project's current stage onward,
        that have a planned date which is currently set on the project."""
        Stage = self.env["project.project.stage"]
        Project = self.env["project.project"]
        has_flags = "pl_for_implementation" in Stage._fields
        for rec in self:
            project = rec.project_id
            if not project:
                rec.allowed_stage_ids = Stage
                continue
            domain = []
            ptype = (
                project.ft_project_type
                if "ft_project_type" in Project._fields
                else False
            )
            flag = self._PROJECT_TYPE_STAGE_FLAG.get(ptype)
            if has_flags and flag and flag in Stage._fields:
                domain.append((flag, "=", True))
            current = rec.stage_id
            if current:
                domain.append(("sequence", ">=", current.sequence))
            stages = Stage.search(domain, order="sequence, id")
            rec.allowed_stage_ids = stages.filtered(
                lambda st: (
                    _stage_planned_date_field(st) in Project._fields
                    and bool(project[_stage_planned_date_field(st)])
                )
            )

    @api.depends("stage_to_extend_id", "project_id")
    def _compute_date_to_extend_id(self):
        """The planned date of the chosen stage (the date it must be reached
        by). Without a stage the legacy value (picked by hand) is kept, so
        older requests, projects with no applicable stage and the Go Live /
        Support End dates (no stage's date) keep working."""
        for rec in self:
            if rec.stage_to_extend_id:
                rec.date_to_extend_id = self._stage_lifecycle_date(
                    rec.stage_to_extend_id
                )
            else:
                rec.date_to_extend_id = rec.date_to_extend_id

    @api.depends("project_id", "date_to_extend_id")
    def _compute_current_date(self):
        """Snapshot of the project's live planned date when the target is
        chosen. Deliberately NOT dependent on the project date itself: a
        draft keeps the value it was raised against; approval refreshes it
        (see _do_approve)."""
        for rec in self:
            rec.current_date = rec._get_source_date()

    @api.depends("requested_date", "current_date")
    def _compute_extension_days(self):
        for rec in self:
            days = 0
            if rec.requested_date and rec.current_date:
                days = (rec.requested_date - rec.current_date).days
            rec.extension_days = days
            rec.is_preponement = days < 0
            rec.delay_days = max(days, 0)

    @api.depends(
        "project_id", "date_to_extend_id", "current_date", "requested_date",
        "is_preponement", "state", "downstream_impact_applied",
    )
    def _compute_downstream_impact(self):
        for rec in self:
            if rec.state == "approved" and rec.downstream_impact_applied:
                # Frozen at approval: the live preview would read the already
                # shifted dates and show nothing.
                rec.downstream_impact = rec.downstream_impact_applied
            else:
                rec.downstream_impact = rec._render_downstream_impact()

    @staticmethod
    def _fmt_date(value):
        return "%d %s" % (value.day, value.strftime("%b %Y")) if value else "-"

    def _render_downstream_impact(self):
        self.ensure_one()
        if not (self.project_id and self.date_to_extend_id and self.requested_date):
            return Markup("<p class='text-muted mb-0'>%s</p>") % _(
                "Select the stage and the rescheduled date to preview the "
                "impact on later dates."
            )
        if self.is_preponement:
            return Markup("<p class='mb-0'>%s</p>") % _(
                "No later dates will change (a preponement only moves the "
                "selected date)."
            )
        gap = self._extension_gap()
        shifts = self._downstream_shifts(gap) if gap > 0 else []
        if not shifts:
            return Markup("<p class='mb-0'>%s</p>") % _(
                "No later planned dates are set."
            )
        items = Markup("").join(
            Markup("<li>%s: %s \u2192 <b>%s</b></li>")
            % (escape(ld.name), self._fmt_date(old), self._fmt_date(new))
            for ld, old, new in shifts
        )
        return Markup("<ul class='mb-0'>%s</ul>") % items

    def _get_source_date(self):
        """Current value of the selected project date."""
        self.ensure_one()
        ld = self.date_to_extend_id
        if ld and self.project_id and ld.field_name in self.project_id._fields:
            return self.project_id[ld.field_name]
        return False

    def _target_label(self):
        self.ensure_one()
        return self.date_to_extend_id.name or _("date")

    def _extension_gap(self):
        """Signed number of days the selected date moves, measured against
        the project's LIVE value (falling back to the frozen current_date
        when the project field is empty). Using the live value is what keeps
        the downstream shift right when the date changed after the request
        was raised."""
        self.ensure_one()
        base = self._get_source_date() or self.current_date
        if base and self.requested_date:
            return (self.requested_date - base).days
        return 0

    def _downstream_shifts(self, gap):
        """[(lifecycle_date, old_value, new_value)] for every lifecycle date
        AFTER the selected one that is set on the project, shifted by ``gap``
        days. Shared by the preview (downstream_impact) and the approval
        (_apply_extension) so the two always agree. Empty for a non-positive
        gap: dates are never shifted backwards."""
        self.ensure_one()
        ld = self.date_to_extend_id
        project = self.project_id
        if not ld or not project or not gap or gap < 0:
            return []
        later = self.env["project.lifecycle.date"].search(
            [("sequence", ">", ld.sequence)]
        )
        shifts = []
        for d in later:
            fname = d.field_name
            if fname in project._fields and project[fname]:
                old = project[fname]
                shifts.append((d, old, old + timedelta(days=gap)))
        return shifts

    def _previous_lifecycle_date(self):
        """(lifecycle_date, value) of the last SET lifecycle date before the
        selected one on the project, or (None, None)."""
        self.ensure_one()
        ld = self.date_to_extend_id
        project = self.project_id
        if not ld or not project:
            return None, None
        earlier = self.env["project.lifecycle.date"].search(
            [("sequence", "<", ld.sequence)], order="sequence desc, id desc"
        )
        for d in earlier:
            if d.field_name in project._fields and project[d.field_name]:
                return d, project[d.field_name]
        return None, None

    def _check_preponement_order(self, new_date=None):
        """A preponement must still respect the step order: the new date may
        not fall before the previous set lifecycle date of the project."""
        for rec in self:
            target = new_date or rec.requested_date
            if not target or not rec.date_to_extend_id:
                continue
            base = rec._get_source_date() or rec.current_date
            if not base or target >= base:
                continue  # not a preponement
            prev, prev_value = rec._previous_lifecycle_date()
            if prev and target < prev_value:
                raise ValidationError(_(
                    "The rescheduled %(target)s (%(date)s) cannot be earlier "
                    "than the previous planned date, %(prev)s (%(prev_date)s). "
                    "The project dates must keep their step order; please "
                    "choose a date on or after %(prev_date)s.",
                    target=rec._target_label(),
                    date=rec._fmt_date(target),
                    prev=prev.name,
                    prev_date=rec._fmt_date(prev_value),
                ))

    def _apply_extension(self):
        """Approve: set the selected date to the requested one.

        Extension (gap > 0): every LATER set lifecycle date is shifted
        forward by the same gap (earlier dates are never touched); the
        write skips the ordering guard since the whole tail moves together.

        Preponement (gap < 0): ONLY the selected date moves - later dates
        are never pulled backwards - and the project's normal step-order
        check runs, so a date that would land before the previous step is
        refused with a ValidationError.

        The gap is measured against the project's LIVE value, not the
        current_date frozen at request time (see _extension_gap).
        """
        self.ensure_one()
        ld = self.date_to_extend_id
        project = self.project_id
        if not ld or not project or ld.field_name not in project._fields:
            return
        gap = self._extension_gap()
        vals = {ld.field_name: self.requested_date}
        if gap > 0:
            for d, _old, new in self._downstream_shifts(gap):
                vals[d.field_name] = new
            project.sudo().with_context(skip_date_sequence_check=True).write(vals)
        else:
            self._check_preponement_order()
            project.sudo().write(vals)

    @api.onchange("project_id")
    def _onchange_project_id(self):
        self.stage_to_extend_id = False
        self.date_to_extend_id = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code(
                        "project.date.extension.request"
                    )
                    or _("New")
                )
            # A request raised by stage (UI or API) targets that stage's
            # planned date (the one it must be reached by). current_date is
            # computed from it and frozen
            # there (see _compute_current_date), so history is not lost
            # even if that date changes afterwards through another
            # approved request.
            if vals.get("stage_to_extend_id") and not vals.get("date_to_extend_id"):
                stage = self.env["project.project.stage"].browse(
                    vals["stage_to_extend_id"]
                )
                vals["date_to_extend_id"] = self._stage_lifecycle_date(stage).id
        return super().create(vals_list)

    @api.constrains("date_to_extend_id", "stage_to_extend_id", "project_id")
    def _check_target_selected(self):
        for rec in self:
            if not rec.date_to_extend_id:
                if rec.stage_to_extend_id:
                    raise ValidationError(_(
                        "Stage %s has no planned date, so it cannot be "
                        "extended. Please choose another stage.",
                        rec.stage_to_extend_id.display_name,
                    ))
                raise ValidationError(
                    _("Please select the Stage to be Extended.")
                )
            # A stage whose planned date is not set on the project has
            # nothing to move (it is not offered in the dropdown either).
            if rec.stage_to_extend_id and not rec._get_source_date():
                raise ValidationError(_(
                    "Stage %(stage)s has no %(date)s set on project "
                    "%(project)s, so it cannot be extended. Please choose "
                    "another stage.",
                    stage=rec.stage_to_extend_id.display_name,
                    date=rec._target_label(),
                    project=rec.project_id.display_name,
                ))

    @api.constrains("project_id", "date_to_extend_id", "stage_to_extend_id",
                    "milestone_id", "state")
    def _check_single_open_request(self):
        """Only one open (Draft / Request) request per project and target
        date: a second one raised while the first is still pending carries a
        Current Date and Extension Days that go stale as soon as the first is
        approved, which misleads the approver."""
        for rec in self:
            if rec.state not in ("draft", "request") or not rec.project_id:
                continue
            domain = [
                ("id", "!=", rec.id),
                ("project_id", "=", rec.project_id.id),
                ("state", "in", ("draft", "request")),
            ]
            if rec.date_to_extend_id:
                domain.append(("date_to_extend_id", "=", rec.date_to_extend_id.id))
                target = rec.date_to_extend_id.display_name
            elif rec.stage_to_extend_id:
                domain.append(("stage_to_extend_id", "=", rec.stage_to_extend_id.id))
                target = rec.stage_to_extend_id.display_name
            elif rec.milestone_id:
                domain.append(("milestone_id", "=", rec.milestone_id.id))
                target = rec.milestone_id.display_name
            else:
                continue
            other = self.sudo().search(domain, limit=1)
            if other:
                raise ValidationError(_(
                    "%(other)s is still pending (%(state)s) for %(target)s of "
                    "project %(project)s. Only one open Date Extension Request "
                    "is allowed per stage: approve or reject it first, or "
                    "update that request instead of raising a new one.",
                    other=other.name,
                    state=dict(other._fields["state"].selection).get(other.state),
                    target=target,
                    project=rec.project_id.display_name,
                ))

    @api.constrains("project_id", "stage_id", "stage_to_extend_id")
    def _check_stage_not_passed(self):
        """Server-side twin of the dropdown: only the project's current stage
        and the stages after it may be extended."""
        for rec in self:
            stage = rec.stage_to_extend_id
            if not stage or rec.state in ("approved", "rejected"):
                continue
            allowed = rec.allowed_stage_ids
            if allowed and stage not in allowed:
                raise ValidationError(_(
                    "Stage %(stage)s has already been passed: project "
                    "%(project)s is in %(current)s. Only the current stage and "
                    "the stages after it can be extended.",
                    stage=stage.display_name, project=rec.project_id.display_name,
                    current=rec.stage_id.display_name or "-"))

    @api.constrains("requested_date", "current_date")
    def _check_requested_date(self):
        for rec in self:
            if rec.requested_date and rec.current_date and (
                rec.requested_date == rec.current_date
            ):
                raise ValidationError(
                    _(
                        "The rescheduled date must be different from the "
                        "current planned date."
                    )
                )

    # ----------------------------------------------------------------
    # Point 4: only authorized Admin users may approve/reject
    # ----------------------------------------------------------------
    def _check_can_decide(self):
        if not self.env.user.has_group(APPROVER_GROUP):
            raise AccessError(
                _(
                    "Only authorized Admin users (member of the 'Date "
                    "Extension Approver' group) can approve or reject "
                    "Project Date Extension Requests."
                )
            )

    # ----------------------------------------------------------------
    # Point 5: approval writes the revised date onto the REAL milestone
    # field (project.custom.milestone.due_date) rather than a parallel
    # copy, so any code that reads it sees the new value at once.
    #
    # Points 6 & 10: that field is exactly what this module's own
    # consumers read - the milestone overdue calc, the project-level
    # overdue rollup and the timesheet cut-off on account.analytic.line
    # all go through project.custom.milestone._ft_effective_deadline()
    # (= due_date). So approving here immediately shifts overdue and the
    # timesheet limit to the new date; no further wiring is needed.
    # ----------------------------------------------------------------
    def action_submit_request(self):
        """Submit a draft for approval (Draft -> Request).

        The assigned requester (or an admin) may submit even though users
        have read-only access to the model: the state change is done with
        sudo, so no general write access is granted. It never changes any
        project/milestone date - only an approver can do that.
        """
        for rec in self:
            if rec.state != "draft":
                raise UserError(
                    _("Only draft requests can be submitted for approval.")
                )
            if not (
                self.env.su
                or self.env.user == rec.requester_id
                or self.env.user.has_group(APPROVER_GROUP)
            ):
                raise AccessError(
                    _(
                        "Only the assigned requester or an administrator "
                        "can submit this request."
                    )
                )
            # A preponement must keep the step order; refuse it up front
            # rather than at approval, with the reason spelled out.
            rec._check_preponement_order()
            rec.sudo().write({"state": "request"})
            rec.sudo().message_post(
                body=_(
                    "Date Extension submitted for approval by %(user)s.",
                    user=self.env.user.name,
                )
            )
        return True

    def _do_approve(self, new_date=None, comment=None):
        self._check_can_decide()
        for rec in self:
            if rec.state != "request":
                raise UserError(
                    _("Only submitted requests (in Request state) can be approved.")
                )
            # Refresh the snapshot from the project FIRST: the gap, the
            # extension days and the history line are all measured against
            # the date as it stands now, not as it stood when the request
            # was raised (it may have moved through another approval).
            live_date = rec._get_source_date()
            pre_vals = {}
            if new_date:
                pre_vals["requested_date"] = new_date
            if live_date and live_date != rec.current_date:
                pre_vals["current_date"] = live_date
            if pre_vals:
                rec.write(pre_vals)
            old_date = live_date or rec.current_date
            # Set the selected date to the requested one; an extension also
            # shifts every later lifecycle date forward by the same gap, a
            # preponement moves the selected date only (see _apply_extension).
            rec.downstream_impact_applied = rec._render_downstream_impact()
            rec._apply_extension()
            vals = {
                "state": "approved",
                "approver_id": self.env.user.id,
                "decision_date": fields.Datetime.now(),
            }
            if comment:
                vals["approval_comment"] = comment
            rec.write(vals)

            body = _(
                "%(kind)s approved by %(user)s. %(target)s changed "
                "from %(old)s to %(new)s (%(days)+d days).",
                kind=_("Preponement") if rec.is_preponement else _("Date Extension"),
                user=self.env.user.name,
                target=rec._target_label(),
                old=old_date,
                new=rec.requested_date,
                days=rec.extension_days,
            )
            if comment:
                body += f"<br/><b>{_('Approval Comment:')}</b> {comment}"
            rec.message_post(body=body)

    def _do_reject(self, comment=None):
        self._check_can_decide()
        for rec in self:
            if rec.state != "request":
                raise UserError(
                    _("Only submitted requests (in Request state) can be rejected.")
                )
            vals = {
                "state": "rejected",
                "approver_id": self.env.user.id,
                "decision_date": fields.Datetime.now(),
            }
            if comment:
                vals["rejection_reason"] = comment
            rec.write(vals)

            body = _(
                "Date Extension rejected by %(user)s.",
                user=self.env.user.name,
            )
            if comment:
                body += f"<br/><b>{_('Rejection Reason:')}</b> {comment}"
            rec.message_post(body=body)

    def action_approve(self):
        self._check_can_decide()
        self.ensure_one()
        if self.env.context.get("skip_wizard"):
            return self._do_approve(
                new_date=self.requested_date,
                comment=self.approval_comment or self.env.context.get("comment"),
            )
        return {
            "name": _("Approve Date Extension"),
            "type": "ir.actions.act_window",
            "res_model": "project.date.extension.decision.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_request_id": self.id,
                "default_decision": "approve",
                "default_requested_date": self.requested_date,
            },
        }

    def action_reject(self):
        self._check_can_decide()
        self.ensure_one()
        if self.env.context.get("skip_wizard"):
            return self._do_reject(
                comment=self.rejection_reason or self.env.context.get("comment"),
            )
        return {
            "name": _("Reject Date Extension"),
            "type": "ir.actions.act_window",
            "res_model": "project.date.extension.decision.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_request_id": self.id,
                "default_decision": "reject",
            },
        }

    def action_reset_to_draft(self):
        """Allow a rejected request to be reworked and resubmitted while
        keeping the rejected copy... actually resets the SAME record, so
        for a full audit trail users should prefer creating a new request
        instead of resetting an existing one."""
        self._check_can_decide()
        for rec in self:
            if rec.state != "rejected":
                raise UserError(
                    _("Only rejected requests can be reset to draft.")
                )
            rec.write(
                {
                    "state": "draft",
                    "approver_id": False,
                    "decision_date": False,
                    "rejection_reason": False,
                    "approval_comment": False,
                }
            )
        return True

    # ----------------------------------------------------------------
    # Point 7: keep the full history - processed requests can't be
    # deleted. Only a mistaken draft (never decided) may be removed.
    # ----------------------------------------------------------------
    def unlink(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(
                    _(
                        "Approved or rejected Date Extension Requests "
                        "cannot be deleted, in order to preserve the full "
                        "extension history."
                    )
                )
        return super().unlink()
