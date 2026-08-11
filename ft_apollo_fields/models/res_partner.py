from odoo import models, fields


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # ------------------------------------------------------------------
    # Apollo.io company enrichment fields
    # ------------------------------------------------------------------
    apollo_company_name_for_emails = fields.Char(string="Company Name for Emails")
    apollo_facebook_url = fields.Char(string="Facebook Url")
    apollo_company_city = fields.Char(string="Company City")
    apollo_company_state = fields.Char(string="Company State")
    apollo_company_country = fields.Char(string="Company Country")
    apollo_keywords = fields.Text(string="Keywords")
    apollo_technologies = fields.Text(string="Technologies")
    founded_year = fields.Char(string="Founded Year")
    # Helper currency for the funding monetary fields (hidden in the UI).
    apollo_currency_id = fields.Many2one(
        'res.currency', string="Currency",
        default=lambda self: self.env.company.currency_id)
    apollo_total_funding = fields.Monetary(
        string="Total Funding", currency_field='apollo_currency_id')
    apollo_latest_funding = fields.Char(string="Latest Funding")
    apollo_latest_funding_amount = fields.Monetary(
        string="Latest Funding Amount", currency_field='apollo_currency_id')
    apollo_last_raised_at = fields.Date(string="Last Raised At")
    apollo_record_id = fields.Char(string="Apollo Record Id")
