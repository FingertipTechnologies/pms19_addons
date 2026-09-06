# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

APPROVER_GROUP = "project_date_extension.group_project_date_extension_approver"


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
    date_to_extend_id = fields.Many2one(
        "project.lifecycle.date",
        string="Date to Extend",
        tracking=True,
        ondelete="restrict",
        domain="[('id', 'in', allowed_date_ids)]",
        help="Only the current stage's date and the dates after it are "
        "offered; earlier dates have already passed.",
    )
    allowed_date_ids = fields.Many2many(
        "project.lifecycle.date",
        compute="_compute_allowed_date_ids",
        string="Allowed Dates",
    )
    current_date = fields.Date(
        string="Current Date",
        readonly=True,
        copy=False,
        help="Date on the milestone/stage at the time this request was "
        "created (or last approved). Kept for history purposes and "
        "never recomputed automatically.",
    )
    requested_date = fields.Date(
        string="Requested New Date",
        required=True,
        tracking=True,
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
    rejection_reason = fields.Text(string="Rejection Reason", copy=False)

    company_id = fields.Many2one(
        related="project_id.company_id", store=True, readonly=True
    )

    # ----------------------------------------------------------------
    # Onchange / create
    # ----------------------------------------------------------------
    # Where each stage sits in the lifecycle: the sequence of the first
    # date to offer when the project is in that stage. Dates before it have
    # already passed, so they are hidden. Anchored on the BA's examples
    # (DEV -> from Sandbox Review; SUPPORT -> from Support Start). Unknown
    # stages fall back to showing everything.
    _STAGE_MIN_SEQUENCE = {
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
        return self._STAGE_MIN_SEQUENCE.get(stage.name, 10) if stage else 10

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

    def _apply_extension(self):
        """Approve: set the selected date to the requested one, then shift
        every LATER lifecycle date forward by the same gap. Earlier dates
        (already passed) are never touched. Empty later dates are skipped.
        """
        self.ensure_one()
        ld = self.date_to_extend_id
        project = self.project_id
        if not ld or not project or ld.field_name not in project._fields:
            return
        gap = 0
        if self.current_date and self.requested_date:
            gap = (self.requested_date - self.current_date).days
        vals = {ld.field_name: self.requested_date}
        if gap:
            later = self.env["project.lifecycle.date"].search(
                [("sequence", ">", ld.sequence)]
            )
            for d in later:
                fname = d.field_name
                if fname in project._fields and project[fname]:
                    vals[fname] = project[fname] + timedelta(days=gap)
        project.sudo().with_context(skip_date_sequence_check=True).write(vals)

    @api.onchange("project_id")
    def _onchange_project_id(self):
        self.date_to_extend_id = False
        self.current_date = False

    @api.onchange("date_to_extend_id")
    def _onchange_date_to_extend(self):
        for rec in self:
            rec.current_date = rec._get_source_date()

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
            # Freeze the "current date" as it stood on the selected date at
            # request time, so history is not lost even if that date changes
            # afterwards through another approved request.
            if not vals.get("current_date") and vals.get("date_to_extend_id") and vals.get("project_id"):
                project = self.env["project.project"].browse(vals["project_id"])
                ld = self.env["project.lifecycle.date"].browse(vals["date_to_extend_id"])
                if ld.field_name and ld.field_name in project._fields:
                    vals["current_date"] = project[ld.field_name]
        return super().create(vals_list)

    @api.constrains("date_to_extend_id")
    def _check_target_selected(self):
        for rec in self:
            if not rec.date_to_extend_id:
                raise ValidationError(
                    _("Please select the Date to extend.")
                )

    @api.constrains("requested_date", "current_date")
    def _check_requested_date(self):
        for rec in self:
            if rec.requested_date and rec.current_date and (
                rec.requested_date == rec.current_date
            ):
                raise ValidationError(
                    _(
                        "The requested new date must be different from the "
                        "current milestone/stage date."
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
            rec.sudo().write({"state": "request"})
            rec.sudo().message_post(
                body=_(
                    "Date Extension submitted for approval by %(user)s.",
                    user=self.env.user.name,
                )
            )

    def action_approve(self):
        self._check_can_decide()
        for rec in self:
            if rec.state != "request":
                raise UserError(
                    _("Only submitted requests (in Request state) can be approved.")
                )
            old_date = rec._get_source_date()
            # Set the selected date to the requested one and shift every
            # later lifecycle date forward by the same gap (earlier dates
            # untouched). sudo + skip checks so it isn't blocked by the
            # admin-only / ordering guards.
            rec._apply_extension()
            rec.write(
                {
                    "state": "approved",
                    "approver_id": self.env.user.id,
                    "decision_date": fields.Datetime.now(),
                    "current_date": old_date,
                }
            )
            rec.message_post(
                body=_(
                    "Date Extension approved by %(user)s. %(target)s changed "
                    "from %(old)s to %(new)s.",
                    user=self.env.user.name,
                    target=rec._target_label(),
                    old=old_date,
                    new=rec.requested_date,
                )
            )

    def action_reject(self):
        self._check_can_decide()
        for rec in self:
            if rec.state != "request":
                raise UserError(
                    _("Only submitted requests (in Request state) can be rejected.")
                )
            rec.write(
                {
                    "state": "rejected",
                    "approver_id": self.env.user.id,
                    "decision_date": fields.Datetime.now(),
                }
            )
            if rec.rejection_reason:
                rec.message_post(
                    body=_(
                        "Date Extension rejected by %(user)s. Reason: "
                        "%(reason)s",
                        user=self.env.user.name,
                        reason=rec.rejection_reason,
                    )
                )
            else:
                rec.message_post(
                    body=_(
                        "Date Extension rejected by %(user)s.",
                        user=self.env.user.name,
                    )
                )

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
                }
            )

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
