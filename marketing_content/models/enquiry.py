# -*- coding: utf-8 -*-
from odoo import fields, models


class MarketingEnquiry(models.Model):
    _name = "marketing.enquiry"
    _description = "Marketing Enquiry"
    _rec_name = "name"
    _order = "create_date desc"

    name = fields.Char(required=True, index=True)
    email = fields.Char(index=True)
    phone = fields.Char(index=True)
    message = fields.Text()
    location = fields.Char()
    company = fields.Char()
    subject = fields.Char()
    domain = fields.Char()
