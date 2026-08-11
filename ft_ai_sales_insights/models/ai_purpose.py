"""Analysis purposes — data, not code.

Each record is one selectable "purpose" with its own editable prompt. Adding a
new analysis type is a matter of creating a record (UI or data file); no Python
change is required, satisfying the "add purposes without changing business
logic" requirement.
"""
from odoo import fields, models
from odoo.exceptions import UserError


class FtAiInsightsPurpose(models.Model):
    _name = "ft.ai.insights.purpose"
    _description = "AI Sales Insights Purpose"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(
        required=True,
        help="Stable technical key (unique). Used by integrations/automation.",
    )
    applies_to = fields.Selection(
        [("sales", "Sales"), ("project", "Project")],
        required=True,
        default="sales",
        help="Which dashboard offers this purpose. Each domain supplies a "
        "different data payload, so a purpose belongs to exactly one.",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    include_milestones = fields.Boolean(
        string="Include Milestone Billing Data",
        default=False,
        help="Project purposes only. Milestones here are a billing lifecycle "
        "(delivered -> invoiced -> paid), not delivery timing, so they are sent "
        "only to purposes that actually analyse revenue. Leaving this off keeps "
        "them out of delivery and per-developer reports.",
    )
    icon = fields.Char(default="fa-line-chart", help="FontAwesome class.")
    description = fields.Char(translate=True)
    prompt = fields.Text(
        required=True,
        translate=True,
        help="Purpose-specific instructions appended to the master prompt.",
    )

    # Odoo 19 replaced _sql_constraints with models.Constraint declarations.
    _code_uniq = models.Constraint(
        "unique(code)",
        "The purpose code must be unique.",
    )

    def _resolve_for(self, applies_to, purpose_id=None, default=None):
        """Pick the purpose to run for ``applies_to``.

        Order: explicit ``purpose_id`` -> configured ``default`` -> first active
        purpose of that domain. Shared by the Sales and Project dashboards so
        both behave identically. A purpose from another domain is ignored rather
        than trusted, since its prompt expects a different payload.
        """
        Purpose = self.env["ft.ai.insights.purpose"]
        domain = [("applies_to", "=", applies_to)]
        purpose = Purpose.browse(int(purpose_id)) if purpose_id else Purpose
        if not purpose or not purpose.exists() or purpose.applies_to != applies_to:
            purpose = default if default and default.applies_to == applies_to else Purpose
        if not purpose:
            purpose = Purpose.search(domain + [("active", "=", True)], limit=1)
        if not purpose:
            raise UserError(
                "No %s analysis purposes are configured. Add one under "
                "AI Insights > Configuration > Purposes." % applies_to
            )
        return purpose
