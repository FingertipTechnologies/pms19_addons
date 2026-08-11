# -*- coding: utf-8 -*-
from odoo import fields, models


class MarketingPageview(models.Model):
    _name = "marketing.pageview"
    _description = "Marketing Pageview"
    _rec_name = "name"
    _order = "create_date desc"

    name = fields.Char(required=True, index=True)
    url = fields.Char(required=True)
    location = fields.Char()
    domain = fields.Char(index=True)
    ip = fields.Char(string="IP", index=True)
