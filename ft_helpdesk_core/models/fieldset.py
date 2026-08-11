from odoo import api, fields, models


class HelpdeskFieldset(models.Model):
    _name = 'ft.helpdesk.fieldset'
    _description = 'Helpdesk Dynamic Fieldset'
    _order = 'name'

    name = fields.Char(string='Fieldset Name', required=True, translate=True)
    active = fields.Boolean(default=True)
    field_ids = fields.One2many(
        'ft.helpdesk.dynamic.field', 'fieldset_id', string='Fields',
    )
    description = fields.Text(string='Description')


class HelpdeskDynamicField(models.Model):
    _name = 'ft.helpdesk.dynamic.field'
    _description = 'Helpdesk Dynamic Field'
    _order = 'sequence, name'

    name = fields.Char(string='Field Label', required=True, translate=True)
    technical_name = fields.Char(
        string='Technical Name', required=True,
        help='Key used in the JSON storage. Use snake_case (e.g., order_number).',
    )
    sequence = fields.Integer(string='Sequence', default=10)
    fieldset_id = fields.Many2one(
        'ft.helpdesk.fieldset', string='Fieldset',
        required=True, ondelete='cascade',
    )
    field_type = fields.Selection([
        ('char', 'Text'),
        ('text', 'Multi-line Text'),
        ('integer', 'Integer'),
        ('float', 'Decimal'),
        ('date', 'Date'),
        ('datetime', 'Date & Time'),
        ('boolean', 'Checkbox'),
        ('selection', 'Dropdown'),
        ('url', 'URL'),
        ('email', 'Email'),
    ], string='Field Type', required=True, default='char')
    selection_options = fields.Text(
        string='Dropdown Options',
        help='One option per line for dropdown fields.',
    )
    required = fields.Boolean(string='Required', default=False)
    portal_visible = fields.Boolean(string='Show on Portal', default=True)
    placeholder = fields.Char(string='Placeholder', translate=True)
    help_text = fields.Char(string='Help Text', translate=True)

    @api.onchange('technical_name')
    def _onchange_technical_name(self):
        if self.technical_name:
            self.technical_name = self.technical_name.strip().lower().replace(' ', '_')
