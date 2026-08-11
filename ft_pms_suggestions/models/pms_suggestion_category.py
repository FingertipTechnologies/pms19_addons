# -*- coding: utf-8 -*-
from odoo import fields, models


class PmsSuggestionCategory(models.Model):
    _name = "pms.suggestion.category"
    _description = "PMS Suggestion Module/Area"
    _order = "sequence, name"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
