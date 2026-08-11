from odoo import api, fields, models


class KBCategory(models.Model):
    _name = 'ft.helpdesk.kb.category'
    _description = 'Knowledge Base Category'
    _order = 'sequence, name'

    name = fields.Char(string='Category Name', required=True, translate=True)
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(default=True)
    description = fields.Text(string='Description', translate=True)
    icon = fields.Char(
        string='Icon Class', default='fa-folder-open',
        help='FontAwesome icon class.',
    )
    color = fields.Integer(string='Color Index')
    portal_published = fields.Boolean(
        string='Published on Portal', default=True,
    )
    parent_id = fields.Many2one(
        'ft.helpdesk.kb.category', string='Parent Category',
        index=True, ondelete='cascade',
    )
    child_ids = fields.One2many(
        'ft.helpdesk.kb.category', 'parent_id', string='Subcategories',
    )
    article_ids = fields.One2many(
        'ft.helpdesk.kb.article', 'category_id', string='Articles',
    )
    article_count = fields.Integer(
        string='Articles', compute='_compute_article_count',
    )

    # Link to helpdesk category for suggestions
    helpdesk_category_id = fields.Many2one(
        'ft.helpdesk.category', string='Related Helpdesk Category',
        help='Link to helpdesk category for ticket creation suggestions.',
    )

    def _compute_article_count(self):
        data = self.env['ft.helpdesk.kb.article'].read_group(
            [('category_id', 'in', self.ids), ('portal_published', '=', True)],
            ['category_id'], ['category_id'],
        )
        mapped = {d['category_id'][0]: d['category_id_count'] for d in data}
        for cat in self:
            cat.article_count = mapped.get(cat.id, 0)
