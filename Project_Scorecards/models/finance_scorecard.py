from odoo import models, fields, api

class FinanceScorecard(models.Model):
    _name = 'finance.scorecard'
    _description = 'Finance Scorecard'
    _rec_name = 'name'

    name = fields.Char(
        string='Scorecard Name',
        compute='_compute_name',
        store=True
    )
    date = fields.Date(
        string='Date',
        default=fields.Date.context_today
    )

    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        required=True,
        default=lambda self: self.env.company.currency_id
    )

    invoice_raised = fields.Integer(string="Invoices Raised")

    raised_amount = fields.Monetary(
        string="Raised Amount",
        currency_field='currency_id'
    )

    collected_amount = fields.Monetary(
        string="Collected Amount",
        currency_field='currency_id'
    )

    outstanding = fields.Monetary(
        string="Outstanding",
        currency_field='currency_id'
    )

    description = fields.Text(
        string="Description"
    )

    @api.depends('date')
    def _compute_name(self):
        for record in self:
            if record.date:
                record.name = f"Finance Scorecard - {record.date}"
            else:
                record.name = "Finance Scorecard"