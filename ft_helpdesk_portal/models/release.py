from odoo import fields, models


class FtHelpdeskRelease(models.Model):
    _name = 'ft.helpdesk.release'
    _description = 'Project Release'
    _order = 'release_date desc, id desc'

    name = fields.Char(string='Release Name', required=True)
    version = fields.Char(string='Version')
    project_id = fields.Many2one(
        'project.project', string='Project', required=True, ondelete='cascade',
    )
    release_date = fields.Date(string='Release Date')
    description = fields.Html(string='Description')
    status = fields.Selection([
        ('planned', 'Planned'),
        ('in_progress', 'In Progress'),
        ('released', 'Released'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='planned')
    notes = fields.Text(string='Internal Notes')
