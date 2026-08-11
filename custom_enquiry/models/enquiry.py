from odoo import models, fields

class Enquiry(models.Model):
    _name = 'x.enquiry'
    _description = 'Website Contact Us Enquiry'
    _order = 'create_date desc'

    x_name    = fields.Char(string='Name', required=True)
    x_phone   = fields.Char(string='Phone')
    x_email   = fields.Char(string='Email', required=True)
    x_company = fields.Char(string='Company')
    x_subject = fields.Char(string='Subject', required=True)
    x_message = fields.Text(string='Message', required=True)