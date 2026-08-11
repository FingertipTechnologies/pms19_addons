# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AssetMaintenance(models.Model):
    _name = "asset.maintenance"
    _description = "Asset Maintenance / Repair"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "issue_date desc, id desc"
    _rec_name = "display_name"

    display_name = fields.Char(
        compute='_compute_display_name', store=True)

    asset = fields.Many2one(
        'company.asset', string="Asset", required=True,
        tracking=True, ondelete='cascade')
    issue_date = fields.Date(
        string="Issue Date", required=True, tracking=True)
    issue_reported_by = fields.Many2one(
        'hr.employee', string="Issue Reported By")
    issue_description = fields.Text(
        string="Issue Description", required=True)
    service_vendor = fields.Many2one(
        'res.partner', string="Service Vendor",
        domain=[('supplier_rank', '>', 0)])
    repair_cost = fields.Monetary(string="Repair Cost")
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id)
    status = fields.Selection(
        selection=[
            ('open', 'Open'),
            ('in_progress', 'In Progress'),
            ('completed', 'Completed'),
            ('cancelled', 'Cancelled'),
        ],
        string="Status", required=True, default='open', tracking=True)
    completion_date = fields.Date(string="Completion Date")
    attachment_ids = fields.Many2many(
        'ir.attachment', 'asset_maintenance_attachment_rel',
        'maintenance_id', 'attachment_id', string="Attachments")
    remarks = fields.Text(string="Remarks")

    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company)

    @api.depends('asset.asset_code', 'issue_date')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = "%s — %s" % (
                rec.asset.asset_code or '',
                rec.issue_date or '')

    def write(self, vals):
        res = super().write(vals)
        # Keep the asset's status in sync when the user changes Status.
        if 'status' in vals:
            for rec in self:
                if rec.status == 'in_progress':
                    rec.asset.current_status = 'under_repair'
                elif rec.status == 'completed':
                    if not rec.completion_date:
                        rec.completion_date = fields.Date.context_today(rec)
                    active_assign = rec.asset.assignment_ids.filtered(
                        lambda a: not a.returned_date)
                    rec.asset.current_status = (
                        'assigned' if active_assign else 'available')
        return res