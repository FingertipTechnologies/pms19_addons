# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class CompanyAsset(models.Model):
    _name = "company.asset"
    _description = "Company Asset"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "asset_code"
    _rec_name = "asset_name"

    # Core
    asset_name = fields.Char(
        string="Asset Name", required=True, tracking=True)
    asset_code = fields.Char(
        string="Asset Code", required=True, copy=False, readonly=True,
        default=lambda self: _('New'), tracking=True)
    category = fields.Many2one(
        'asset.category', string="Category", required=True,
        tracking=True, ondelete='restrict')
    brand = fields.Char(string="Brand")
    model = fields.Char(string="Model")
    serial_number = fields.Char(string="Serial Number", tracking=True)
    imei_number = fields.Char(string="IMEI Number")

    # Specs (for laptops/desktops/phones)
    processor = fields.Char(string="Processor")
    ram = fields.Char(string="RAM")
    storage = fields.Char(string="Storage")
    operating_system_software = fields.Char(string="Operating System / Software")

    # Purchase Details
    purchase_date = fields.Date(string="Purchase Date")
    purchase_vendor = fields.Many2one(
        'res.partner', string="Purchase Vendor",
        domain=[('supplier_rank', '>', 0)])
    invoice_number = fields.Char(string="Invoice Number")
    purchase_cost = fields.Monetary(string="Purchase Cost")
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id)

    # Warranty
    warranty_start_date = fields.Date(string="Warranty Start Date")
    warranty_end_date = fields.Date(string="Warranty End Date", tracking=True)

    # Status
    current_status = fields.Selection(
        selection=[
            ('available', 'Available'),
            ('assigned', 'Assigned'),
            ('under_repair', 'Under Repair'),
            ('lost', 'Lost'),
            ('sold', 'Sold'),
            ('scrapped', 'Scrapped'),
        ],
        string="Current Status", required=True, default='available',
        tracking=True)
    current_employee = fields.Many2one(
        'hr.employee', string="Current Employee",
        compute='_compute_current_employee', store=True, tracking=True)
    department = fields.Many2one('hr.department', string="Department")
    location = fields.Char(string="Location")
    asset_condition = fields.Selection(
        selection=[
            ('new', 'New'),
            ('good', 'Good'),
            ('average', 'Average'),
            ('damaged', 'Damaged'),
        ],
        string="Asset Condition", default='good', tracking=True)

    # Documents
    attachment_ids = fields.Many2many(
        'ir.attachment', 'company_asset_attachment_rel',
        'asset_id', 'attachment_id', string="Attachments")
    remarks = fields.Text(string="Remarks")

    # Relationships
    assignment_ids = fields.One2many(
        'asset.assignment', 'asset', string="Assignments")
    maintenance_ids = fields.One2many(
        'asset.maintenance', 'asset', string="Maintenance Records")
    assignment_count = fields.Integer(
        compute='_compute_counts', string="Assignment Count")
    maintenance_count = fields.Integer(
        compute='_compute_counts', string="Maintenance Count")

    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company)
    active = fields.Boolean(default=True)

    _asset_code_uniq = models.Constraint(
        "unique(asset_code, company_id)",
        "Asset code must be unique per company.",
    )

    # --------------------------------------------------------------
    # CRUD
    # --------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('asset_code', _('New')) == _('New'):
                category = self.env['asset.category'].browse(
                    vals.get('category'))
                prefix = category.asset_code_prefix or 'AST'
                seq = self.env['ir.sequence'].next_by_code(
                    'pms.company.asset') or '0000'
                vals['asset_code'] = "%s-%s" % (prefix, seq)
        return super().create(vals_list)

    # --------------------------------------------------------------
    # Computed
    # --------------------------------------------------------------
    @api.depends('assignment_ids.returned_date',
                 'assignment_ids.employee')
    def _compute_current_employee(self):
        for asset in self:
            active = asset.assignment_ids.filtered(
                lambda a: not a.returned_date)
            asset.current_employee = active[:1].employee or False

    @api.depends('assignment_ids', 'maintenance_ids')
    def _compute_counts(self):
        for asset in self:
            asset.assignment_count = len(asset.assignment_ids)
            asset.maintenance_count = len(asset.maintenance_ids)

    # --------------------------------------------------------------
    # Smart-button actions
    # --------------------------------------------------------------
    def action_view_assignments(self):
        self.ensure_one()
        return {
            'name': _('Assignments'),
            'type': 'ir.actions.act_window',
            'res_model': 'asset.assignment',
            'view_mode': 'list,form',
            'domain': [('asset', '=', self.id)],
            'context': {'default_asset': self.id},
        }

    def action_view_maintenance(self):
        self.ensure_one()
        return {
            'name': _('Maintenance'),
            'type': 'ir.actions.act_window',
            'res_model': 'asset.maintenance',
            'view_mode': 'list,form',
            'domain': [('asset', '=', self.id)],
            'context': {'default_asset': self.id},
        }
