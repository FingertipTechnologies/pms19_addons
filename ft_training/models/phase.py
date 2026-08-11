from odoo import models, fields, _


class Phase(models.Model):
    _name = 'ft.phase'
    _description = 'Training Phase'
    _order = 'sequence, id'

    name = fields.Char(string='Name', required=True)
    sequence = fields.Integer(string='Sequence', default=1)

    def _compute_display_name(self):
        # Odoo 19 removed name_get(); display_name is computed instead.
        for rec in self:
            label = rec.name or _("Phase")
            rec.display_name = f"Phase {rec.sequence} - {label}"
