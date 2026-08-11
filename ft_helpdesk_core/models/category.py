from odoo import api, fields, models


class HelpdeskCategory(models.Model):
    _name = 'ft.helpdesk.category'
    _description = 'Helpdesk Category'
    _order = 'sequence, name'

    name = fields.Char(string='Category Name', required=True, translate=True)
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(default=True)
    parent_id = fields.Many2one(
        'ft.helpdesk.category', string='Parent Category',
        index=True, ondelete='cascade',
    )
    child_ids = fields.One2many(
        'ft.helpdesk.category', 'parent_id', string='Subcategories',
    )
    portal_visible = fields.Boolean(
        string='Visible on Portal', default=True,
        help='Show this category on the portal ticket creation form.',
    )
    description = fields.Text(string='Description', translate=True)
    icon = fields.Char(
        string='Icon Class', default='fa-folder',
        help='FontAwesome icon class (e.g., fa-cog, fa-bug, fa-question-circle)',
    )
    color = fields.Integer(string='Color Index')
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company,
    )
    ticket_count = fields.Integer(
        string='Ticket Count', compute='_compute_ticket_count',
    )
    complete_name = fields.Char(
        string='Complete Name', compute='_compute_complete_name', store=True,
    )

    @api.depends('name', 'parent_id.complete_name')
    def _compute_complete_name(self):
        for category in self:
            if category.parent_id:
                category.complete_name = '%s / %s' % (
                    category.parent_id.complete_name, category.name)
            else:
                category.complete_name = category.name

    def _compute_ticket_count(self):
        data = self.env['ft.helpdesk.ticket'].read_group(
            [('category_id', 'in', self.ids)],
            ['category_id'], ['category_id'],
        )
        mapped = {d['category_id'][0]: d['category_id_count'] for d in data}
        for cat in self:
            cat.ticket_count = mapped.get(cat.id, 0)


class HelpdeskSubcategory(models.Model):
    _name = 'ft.helpdesk.subcategory'
    _description = 'Helpdesk Subcategory'
    _order = 'sequence, name'

    name = fields.Char(string='Subcategory Name', required=True, translate=True)
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(default=True)
    category_id = fields.Many2one(
        'ft.helpdesk.category', string='Parent Category',
        required=True, ondelete='cascade', index=True,
    )
    portal_visible = fields.Boolean(string='Visible on Portal', default=True)
    description = fields.Text(string='Description', translate=True)
