# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProjectProject(models.Model):
    _inherit = "project.project"

    ft_feedback_monthly_enabled = fields.Boolean(
        string="Monthly Customer Feedback",
        default=False,
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
        help="Customer contacts who receive the monthly feedback request.",
    )
    ft_feedback_request_ids = fields.One2many(
        "ft.feedback.request", "project_id", string="Feedback Requests"
    )
    ft_feedback_request_count = fields.Integer(
        string="Feedback Requests",
        compute="_compute_ft_feedback_request_count",
    )

    def _compute_ft_feedback_request_count(self):
        # sudo: the count is shown to project users who may not have access
        # to the feedback requests themselves.
        data = self.env["ft.feedback.request"].sudo()._read_group(
            [("project_id", "in", self.ids)], ["project_id"], ["__count"]
        )
        counts = {project.id: count for project, count in data}
        for project in self:
            project.ft_feedback_request_count = counts.get(project.id, 0)

    @api.constrains("ft_feedback_monthly_enabled", "ft_feedback_contact_ids", "partner_id")
    def _check_ft_feedback_contacts(self):
        for project in self:
            customer = project.partner_id.commercial_partner_id
            if project.ft_feedback_monthly_enabled:
                if not customer:
                    raise ValidationError(_(
                        "Project %(project)s: set a customer before enabling "
                        "monthly customer feedback.",
                        project=project.display_name,
                    ))
                if not project.ft_feedback_contact_ids:
                    raise ValidationError(_(
                        "Project %(project)s: select at least one feedback "
                        "contact to enable monthly customer feedback.",
                        project=project.display_name,
                    ))
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
