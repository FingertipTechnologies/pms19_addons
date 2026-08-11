from odoo import models, fields


class LearningTopic(models.Model):
    _name = 'ft.learning.topic'
    _description = 'Learning Topic'
    _order = 'domain, name'

    name = fields.Char(string='Title', required=True)
    domain = fields.Selection(
        selection=[
            ('salesforce', 'Salesforce'),
            ('odoo', 'Odoo'),
            ('python', 'Python'),
            ('qa', 'QA'),
            ('sales', 'Sales'),
            ('marketing', 'Marketing'),
        ],
        string='Domain',
        required=True,
    )
    phase_id = fields.Many2one('ft.phase', string='Phase', ondelete='restrict')
    day = fields.Integer(string='Day')
    description = fields.Text(string='Description')
    active = fields.Boolean(default=True)
