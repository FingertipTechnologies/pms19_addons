from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class Evaluation(models.Model):
    _name = 'ft.evaluation'
    _description = 'Evaluation'
    _order = 'create_date desc'
    _rec_name = 'trainee_id'

    assignment_id = fields.Many2one(
        'ft.assignment', string='Assignment', required=True, ondelete='restrict',
    )
    trainee_id = fields.Many2one(
        'hr.employee', string='Trainee', required=True, ondelete='restrict',
    )
    rating = fields.Integer(string='Rating', help='Rated 0 to 100.')

    @api.constrains('rating')
    def _check_rating(self):
        for rec in self:
            if rec.rating < 0 or rec.rating > 100:
                raise ValidationError(_("Rating must be between 0 and 100."))
