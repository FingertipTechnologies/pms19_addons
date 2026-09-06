from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
APPROVER_GROUP = "project_date_extension.group_project_date_extension_approver"


class ProjectProject(models.Model):
    _inherit = "project.project"

    # Point 8: related section / smart button showing all Date Extension
    # Requests for that Project.
    date_extension_request_ids = fields.One2many(
        "project.date.extension.request",
        "project_id",
        string="Date Extension Requests",
    )
    date_extension_request_count = fields.Integer(
        compute="_compute_date_extension_request_count"
    )

    # Point 6 (stage validation): a project-level view of overdue
    # milestones, computed from each milestone's (possibly extended)
    # due_date. Any stage/gatekeeping logic can read these instead of
    # re-deriving dates, so an approved extension is honoured here too.
    date_ext_milestone_ids = fields.One2many(
        "project.custom.milestone",
        "project_id",
        string="Project Milestones (Date Extension)",
    )
    overdue_milestone_count = fields.Integer(
        compute="_compute_overdue_milestone_count",
    )
    has_overdue_milestone = fields.Boolean(
        compute="_compute_overdue_milestone_count",
    )

    @api.depends("date_ext_milestone_ids.is_overdue")
    def _compute_overdue_milestone_count(self):
        for project in self:
            overdue = project.date_ext_milestone_ids.filtered("is_overdue")
            project.overdue_milestone_count = len(overdue)
            project.has_overdue_milestone = bool(overdue)

    @api.depends("date_extension_request_ids")
    def _compute_date_extension_request_count(self):
        for project in self:
            project.date_extension_request_count = len(
                project.date_extension_request_ids
            )

    def action_view_date_extension_requests(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "project_date_extension.action_project_date_extension_request"
        )
        action.update(
            {
                "domain": [("project_id", "=", self.id)],
                "context": {
                    **self.env.context,
                    "default_project_id": self.id,
                },
            }
        )
        return action

    # ------------------------------------------------------------------
    # Lifecycle DATES must move forward, step by step (1 -> 12)
    # ------------------------------------------------------------------
    # Each filled date must be on or after the previous filled one. A date
    # earlier than an earlier step (a "past" date in the sequence) is
    # rejected. Fields are matched by LABEL, so it adapts to whatever
    # technical names your lifecycle/customization modules use and skips
    # any label that isn't present. Adjust the order/labels if needed.
    _SEQUENCED_DATE_LABELS = (
        "Start Date",            # 1
        "Kick-off Date",         # 2
        "BRD Approval Date",     # 3
        "Regression Date",       # 4
        "Sandbox Review Date",   # 5
        "UAT Start Date",        # 6
        "Data Upload Date",      # 7
        "Training Date",         # 8
        "Go Live Date",          # 9
        "Support Start Date",    # 10
        "Support End Date",      # 11
        "Closed Date",           # 12
    )

    def _sequenced_date_fields(self):
        """[(technical_name, label), ...] in step order, for fields present."""
        wanted = list(self._SEQUENCED_DATE_LABELS)
        by_label = {}
        for name, field in self._fields.items():
            if field.type == "date" and field.string in wanted:
                by_label.setdefault(field.string, name)
        return [(by_label[label], label)
                for label in wanted if label in by_label]

    def _check_date_sequence(self):
        for project in self:
            prev_label = prev_date = None
            for fname, label in project._sequenced_date_fields():
                value = project[fname]
                if not value:
                    continue
                if prev_date and value < prev_date:
                    raise ValidationError(_(
                        "\"%(label)s\" (%(date)s) is earlier than "
                        "\"%(prev_label)s\" (%(prev_date)s).\n\n"
                        "The project dates must move forward step by step - "
                        "each date has to be on or after the one before it. "
                        "Please enter a later date.",
                        label=label,
                        date=value,
                        prev_label=prev_label,
                        prev_date=prev_date,
                    ))
                prev_label, prev_date = label, value

    # Only admins (Date Extension Approvers) may create or change the
    # controlled lifecycle dates. Superuser and sudo writes (e.g. the
    # Kick-off auto-sync) are exempt.
    def _check_date_edit_permission(self, vals):
        if self.env.su or self.env.user.has_group(APPROVER_GROUP):
            return
        sequenced = {name for name, _label in self._sequenced_date_fields()}
        touched = sorted(sequenced & set(vals))
        if touched:
            labels = dict(
                (name, label)
                for name, label in self._sequenced_date_fields()
            )
            raise AccessError(_(
                "Only administrators can create or change the project "
                "lifecycle dates (%s). Please ask an administrator to set "
                "them.",
                ", ".join(labels.get(name, name) for name in touched),
            ))

    @api.model_create_multi
    def create(self, vals_list):
        today = fields.Date.context_today(self)
        for vals in vals_list:
            # validate any user-provided controlled dates first...
            self._check_date_edit_permission(vals)
            # ...then default Start Date and Kick-off Date to today when the
            # project is created without them (auto value, not a user edit,
            # so it isn't subject to the admin-only date rule).
            if "date_start" in self._fields and not vals.get("date_start"):
                vals["date_start"] = today
            if (
                "kick_start_meeting_date" in self._fields
                and not vals.get("kick_start_meeting_date")
            ):
                vals["kick_start_meeting_date"] = today
        projects = super().create(vals_list)
        projects._check_date_sequence()
        return projects

    def write(self, vals):
        self._check_date_edit_permission(vals)
        res = super().write(vals)
        if not self.env.context.get("skip_date_sequence_check"):
            sequenced_names = {
                name for name, _label in self._sequenced_date_fields()
            }
            if sequenced_names & set(vals):
                self._check_date_sequence()
        return res
