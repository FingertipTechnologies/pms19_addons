# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProjectProject(models.Model):
    _inherit = "project.project"

    ft_feedback_monthly_enabled = fields.Boolean(
        string="Monthly Customer Feedback",
        default=True,
        copy=False,
        help="On the 1st of every month, request feedback for the previous "
        "month from the feedback contacts.",
    )
    ft_feedback_contact_ids = fields.Many2many(
        "res.partner",
        "ft_feedback_project_contact_rel",
        "project_id",
        "partner_id",
        string="Feedback Contacts",
        compute="_compute_ft_feedback_contact_ids",
        store=True,
        readonly=False,
        help="Customer contacts who receive the monthly feedback request. "
        "Defaults to the project customer.",
    )
    ft_feedback_request_ids = fields.One2many(
        "ft.feedback.request", "project_id", string="Feedback Requests"
    )
    ft_feedback_request_count = fields.Integer(
        string="Feedback Requests",
        compute="_compute_ft_feedback_request_count",
    )

    @api.depends("partner_id")
    def _compute_ft_feedback_contact_ids(self):
        # Default to the project customer; keep contacts that still belong
        # to the customer, drop the others when the customer changes.
        for project in self:
            customer = project.partner_id.commercial_partner_id
            contacts = project.ft_feedback_contact_ids.filtered(
                lambda p: customer and p.commercial_partner_id == customer
            )
            project.ft_feedback_contact_ids = contacts or project.partner_id

    def _compute_ft_feedback_request_count(self):
        # sudo: the count is shown to project users who may not have access
        # to the feedback requests themselves.
        data = self.env["ft.feedback.request"].sudo()._read_group(
            [("project_id", "in", self.ids)], ["project_id"], ["__count"]
        )
        counts = {project.id: count for project, count in data}
        for project in self:
            project.ft_feedback_request_count = counts.get(project.id, 0)

    # Enabled by default on every project: a project without a customer or
    # feedback contacts is simply skipped by the monthly cron, so neither is
    # required to switch it on.
    @api.constrains("ft_feedback_contact_ids", "partner_id")
    def _check_ft_feedback_contacts(self):
        for project in self:
            customer = project.partner_id.commercial_partner_id
            wrong = project.ft_feedback_contact_ids.filtered(
                lambda p: p.commercial_partner_id != customer
            )
            if wrong:
                raise ValidationError(_(
                    "Project %(project)s: feedback contacts must belong to the "
                    "project customer (%(customer)s): %(contacts)s.",
                    project=project.display_name,
                    customer=customer.display_name or _("none"),
                    contacts=", ".join(wrong.mapped("display_name")),
                ))

    def _ft_feedback_is_active_customer_project(self):
        """True when monthly feedback must be requested for this project."""
        self.ensure_one()
        if not (self.active and self.partner_id and self.ft_feedback_monthly_enabled):
            return False
        closed_stage = self.env.ref(
            "ft_project_lifecycle.stage_closed", raise_if_not_found=False
        )
        if closed_stage and "stage_id" in self._fields and self.stage_id == closed_stage:
            return False
        if "pl_on_hold" in self._fields and self.pl_on_hold:
            return False
        if "status" in self._fields and self.status in ("closed", "hold"):
            return False
        return True

    def action_view_ft_feedback_requests(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Feedback Requests"),
            "res_model": "ft.feedback.request",
            "view_mode": "list,form",
            "domain": [("project_id", "=", self.id)],
            "context": {"default_project_id": self.id, "create": False},
        }
