from odoo import models, fields

class ProjectCustomMilestone(models.Model):
    _name = 'project.custom.milestone'
    _description = 'Project Custom Milestone'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    # Fields
    project_id = fields.Many2one(
        'project.project',
        string='Project',
        required=True
    )

    sale_order_id = fields.Many2one(
        'sale.order',
        string='Sale Order'
    )

    name = fields.Char(
        string='Milestone Name',
        required=True
    )

    description = fields.Text(
        string='Description'
    )

    amount = fields.Float(
        string='Amount'
    )

    percentage = fields.Float(
        string='Percentage'
    )

    due_date = fields.Date(
        string='Due Date'
    )

    status = fields.Selection(
        [
            ('not_started', 'Not Started'),
            ('completed', 'Completed'),
            ('invoice_raised', 'Invoice Raised'),
            ('partially_paid', 'Partially Paid'),
            ('paid', 'Paid'),
        ],
        string='Status',
        default='not_started'
    )

    milestone_id = fields.Char(
        string='Milestone ID'
    )

    paid_amount = fields.Float(
        string='Paid Amount'
    )

    hours_spent = fields.Float(
        string='Hours Spent'
    )

    attachment_ids = fields.Many2many(
        'ir.attachment',
        'project_custom_milestone_attachment_rel',
        'milestone_id', 'attachment_id',
        string='Attachments'
    )
