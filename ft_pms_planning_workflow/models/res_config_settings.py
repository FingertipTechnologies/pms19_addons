# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pwf_stage_notify_partner_ids = fields.Many2many(
        related='company_id.pwf_stage_notify_partner_ids', readonly=False)
    pwf_stage_notify_email = fields.Char(
        related='company_id.pwf_stage_notify_email', readonly=False)
