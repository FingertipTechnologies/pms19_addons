# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import _, api, fields, models
from odoo.exceptions import AccessError

APPROVER_GROUP = "project_date_extension.group_project_date_extension_approver"


class ProjectCustomMilestone(models.Model):
    """Extends the custom milestone model provided by
    project_custom_milestone (model 'project.custom.milestone', field
    'due_date') instead of the core 'project.milestone' model."""

    _inherit = "project.custom.milestone"

    extension_request_ids = fields.One2many(
        "project.date.extension.request",
        "milestone_id",
        string="Date Extension Requests",
    )
    extension_request_count = fields.Integer(
        compute="_compute_extension_request_count"
    )
    is_date_extension_approver = fields.Boolean(
        compute="_compute_is_date_extension_approver",
        help="Technical field used to let only Date Extension Approvers "
        "edit the due date directly from the milestone list/form.",
    )

    # --- Point 6: overdue calculation driven by the (extended) due_date --
    # After an extension is approved, due_date holds the new date, so both
    # of these recompute against the revised date automatically. A
    # milestone that is already Completed/Paid is never flagged overdue.
    is_overdue = fields.Boolean(
        string="Overdue",
        compute="_compute_overdue",
        search="_search_is_overdue",
        help="True when the milestone is past its Due Date and not yet "
        "Completed/Paid. Uses the extended date once an extension is "
        "approved.",
    )
    days_overdue = fields.Integer(
        string="Days Overdue",
        compute="_compute_overdue",
    )

    _DONE_STATUSES = ("completed", "paid")

    def _ft_effective_deadline(self):
        """Points 6 & 10: the single controlled date for this milestone/stage.

        Approving a Date Extension writes the new date straight onto
        ``due_date`` (see project.date.extension.request.action_approve),
        so the latest approved extension is already folded in here. The
        overdue calc and the timesheet cut-off both read this one method -
        the only place to change should the effective date ever need
        different semantics (e.g. max of all approved extensions).
        """
        self.ensure_one()
        return self.due_date

    @api.depends("due_date", "status")
    def _compute_overdue(self):
        today = fields.Date.context_today(self)
        for milestone in self:
            deadline = milestone._ft_effective_deadline()
            done = milestone.status in self._DONE_STATUSES
            if deadline and not done and deadline < today:
                milestone.is_overdue = True
                milestone.days_overdue = (today - deadline).days
            else:
                milestone.is_overdue = False
                milestone.days_overdue = 0

    def _search_is_overdue(self, operator, value):
        if operator not in ("=", "!=") or not isinstance(value, bool):
            raise ValueError(_("Unsupported search on 'is_overdue'."))
        today = fields.Date.context_today(self)
        overdue_domain = [
            ("due_date", "!=", False),
            ("due_date", "<", today),
            ("status", "not in", list(self._DONE_STATUSES)),
        ]
        looking_for_overdue = (operator == "=" and value) or (
            operator == "!=" and not value
        )
        if looking_for_overdue:
            return overdue_domain
        # De Morgan negation of (A and B and C)
        return [
            "|",
            "|",
            ("due_date", "=", False),
            ("due_date", ">=", today),
            ("status", "in", list(self._DONE_STATUSES)),
        ]

    @api.depends("extension_request_ids")
    def _compute_extension_request_count(self):
        for milestone in self:
            milestone.extension_request_count = len(
                milestone.extension_request_ids
            )

    def _compute_is_date_extension_approver(self):
        is_approver = self.env.user.has_group(APPROVER_GROUP)
        for milestone in self:
            milestone.is_date_extension_approver = is_approver

    # ------------------------------------------------------------
    # Keep the project's "Kick-off Date" on the LATEST milestone date
    # ------------------------------------------------------------
    # The project field kick_start_meeting_date (label "Kick-off Date")
    # mirrors the maximum Due Date across that project's milestones. An
    # approved Date Extension writes the new date onto a milestone's
    # due_date, so the Kick-off Date follows the extended date on its own.
    # The write is guarded: if kick_start_meeting_date is not installed
    # (module not present) it does nothing, and it never clears a value
    # when the project has no dated milestones.
    _KICKOFF_FIELD = "kick_start_meeting_date"

    def _sync_project_kickoff(self, projects):
        Project = self.env["project.project"]
        field = self._KICKOFF_FIELD
        if field not in Project._fields:
            return
        Milestone = self.env["project.custom.milestone"].sudo()
        for project in projects:
            if not project:
                continue
            dated = Milestone.search([
                ("project_id", "=", project.id),
                ("due_date", "!=", False),
            ])
            if not dated:
                continue
            latest = max(dated.mapped("due_date"))
            if project[field] != latest:
                project.sudo().with_context(
                    skip_date_sequence_check=True
                ).write({field: latest})

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_project_kickoff(records.mapped("project_id"))
        return records

    def unlink(self):
        projects = self.mapped("project_id")
        res = super().unlink()
        self._sync_project_kickoff(projects)
        return res

    # ------------------------------------------------------------
    # Point 9: normal users cannot change a controlled milestone date
    # directly - it must go through the Date Extension approval flow.
    # Admin users (members of the approver group) keep direct edit
    # rights, as does the approval flow itself (via the
    # 'date_extension_approval' context key) and technical/superuser
    # operations (installation, migrations, automated tests, ...).
    # ------------------------------------------------------------
    def write(self, vals):
        if (
            "due_date" in vals
            and not self.env.su
            and not self.env.context.get("date_extension_approval")
            and not self.env.user.has_group(APPROVER_GROUP)
        ):
            raise AccessError(
                _(
                    "You are not allowed to change a milestone due date "
                    "directly. Please submit a Date Extension Request "
                    "and have it approved instead."
                )
            )
        projects_before = self.mapped("project_id")
        res = super().write(vals)
        if {"due_date", "project_id"} & set(vals):
            # sync both the old and the new project when a milestone moves
            self._sync_project_kickoff(projects_before | self.mapped("project_id"))
        return res

    def action_view_extension_requests(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "project_date_extension.action_project_date_extension_request"
        )
        action.update(
            {
                "domain": [("milestone_id", "=", self.id)],
                "context": {
                    **self.env.context,
                    "default_project_id": self.project_id.id,
                    "default_milestone_id": self.id,
                },
            }
        )
        return action
