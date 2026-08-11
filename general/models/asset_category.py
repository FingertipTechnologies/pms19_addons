# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AssetCategory(models.Model):
    _name = "asset.category"
    _description = "Asset Category"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "category_name"
    _rec_name = "category_name"

    category_name = fields.Char(
        string="Category Name", required=True, tracking=True)
    asset_code_prefix = fields.Char(
        string="Asset Code Prefix", required=True, tracking=True,
        help="Used as the prefix for the asset's automatic sequence "
             "(e.g. LAP for LAP-0001).")
    depreciation_applicable = fields.Boolean(
        string="Depreciation Applicable", default=False, tracking=True)
    useful_life_in_months = fields.Integer(
        string="Useful Life (Months)", default=36)
    description = fields.Text(string="Description")
    active = fields.Boolean(default=True)

    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company)

    _category_name_uniq = models.Constraint(
        "unique(category_name, company_id)",
        "Asset category name must be unique per company.",
    )

    @api.depends('category_name', 'asset_code_prefix')
    def _compute_display_name(self):
        for rec in self:
            if rec.asset_code_prefix:
                rec.display_name = "%s (%s)" % (
                    rec.category_name or '', rec.asset_code_prefix)
            else:
                rec.display_name = rec.category_name or ''