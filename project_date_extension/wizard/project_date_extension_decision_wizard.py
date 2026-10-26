# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class ProjectDateExtensionDecisionWizard(models.TransientModel):
    _name = "project.date.extension.decision.wizard"
    _description = "Project Date Extension Decision Wizard"

    request_id = fields.Many2one(
        "project.date.extension.request",
        string="Date Extension Request",
        required=True,
        ondelete="cascade",
    )
    decision = fields.Selection(
        [
            ("approve", "Approve"),
            ("reject", "Reject"),
        ],
        string="Decision",
        required=True,
        default="approve",
    )
    current_date = fields.Date(
        string="Current Date",
        related="request_id.current_date",
        readonly=True,
    )
    requested_date = fields.Date(
        string="Approved New Date",
        help="Date to set upon approval. You can keep the requested date or set a different date.",
    )
    comment = fields.Text(
        string="Comment / Reason",
        required=True,
        help="Comment or reason for this decision.",
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        req_id = res.get("request_id") or self.env.context.get("default_request_id")
        if req_id:
            req = self.env["project.date.extension.request"].browse(req_id)
            if "requested_date" in fields_list and not res.get("requested_date"):
                res["requested_date"] = req.requested_date
        return res

    def action_confirm(self):
        self.ensure_one()
        if not self.comment or not self.comment.strip():
            raise ValidationError(_("Please provide a comment for this decision."))

        if self.decision == "approve":
            if not self.requested_date:
                raise ValidationError(_("Please specify the approved new date."))
            if self.current_date and self.requested_date == self.current_date:
                raise ValidationError(
                    _("The approved new date must be different from the current date.")
                )
            self.request_id._do_approve(
                new_date=self.requested_date,
                comment=self.comment.strip(),
            )
        elif self.decision == "reject":
            self.request_id._do_reject(
                comment=self.comment.strip(),
            )
        return {"type": "ir.actions.act_window_close"}
