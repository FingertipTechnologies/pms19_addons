from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

DOMAIN_SELECTION = [
    ('salesforce', 'Salesforce'),
    ('odoo', 'Odoo'),
    ('python', 'Python'),
    ('react', 'React'),
    ('flutter', 'flutter'),
    ('react_native', 'ReactNative'),
]


class Assignment(models.Model):
    _name = 'ft.assignment'
    _description = 'Assignment'
    _order = 'deadline desc, id desc'
    # Assignments are identified by their Title everywhere they are referenced
    # (Evaluation, Review, …). Also makes name_search match on the title.
    _rec_name = 'title'

    title = fields.Char(string='Title')
    description = fields.Text(string='Description')
    deadline = fields.Date(string='Deadline')
    marks = fields.Integer(string='Marks', help='Maximum marks, rated 0 to 100.')
    domain = fields.Selection(
        DOMAIN_SELECTION, string='Domain',
    )
    phase_id = fields.Many2one('ft.phase', string='Phase', ondelete='restrict')

    @api.constrains('marks')
    def _check_marks(self):
        for rec in self:
            if rec.marks < 0 or rec.marks > 100:
                raise ValidationError(_("Marks must be between 0 and 100."))

    @api.depends('title', 'domain')
    def _compute_display_name(self):
        """Show the assignment's Title wherever it is referenced.

        Replaces the old ``name_get`` override, which Odoo 18 no longer calls —
        that is why assignments were displaying the raw domain value ("odoo")
        instead of a readable name.
        """
        for rec in self:
            title = (rec.title or '').strip()
            # Assignments created before the Title field existed have none;
            # fall back to the domain label so they stay identifiable.
            rec.display_name = (
                title or dict(DOMAIN_SELECTION).get(rec.domain) or _("Assignment")
            )
