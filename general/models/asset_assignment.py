# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AssetAssignment(models.Model):
    _name = "asset.assignment"
    _description = "Asset Assignment"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "assigned_date desc, id desc"
    _rec_name = "display_name"

    display_name = fields.Char(
        compute='_compute_display_name', store=True)

    asset = fields.Many2one(
        'company.asset', string="Asset", required=True,
        tracking=True, ondelete='cascade')
    employee = fields.Many2one(
        'hr.employee', string="Employee", required=True, tracking=True)
    assigned_date = fields.Date(
        string="Assigned Date", required=True, tracking=True)
    returned_date = fields.Date(string="Returned Date", tracking=True)
    issued_by = fields.Many2one(
        'res.users', string="Issued By",
        default=lambda self: self.env.user)
    return_condition = fields.Selection(
        selection=[
            ('good', 'Good'),
            ('damaged', 'Damaged'),
            ('missing_parts', 'Missing Parts'),
        ],
        string="Return Condition")
    handover_notes = fields.Text(string="Handover Notes")
    return_notes = fields.Text(string="Return Notes")
    acknowledgement_attachment = fields.Many2many(
        'ir.attachment', 'asset_assignment_attachment_rel',
        'assignment_id', 'attachment_id',
        string="Acknowledgement Attachment")

    is_active = fields.Boolean(
        compute='_compute_is_active', store=True,
        string="Currently Assigned")

    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company)

    @api.constrains('returned_date', 'assigned_date')
    def _check_returned_date(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.returned_date:
                # Returned date cannot be in the future
                if rec.returned_date > today:
                    raise UserError(_(
                        "Returned Date cannot be a future date."))
                # Returned date cannot be before the assigned date
                if rec.assigned_date and \
                        rec.returned_date < rec.assigned_date:
                    raise UserError(_(
                        "Returned Date cannot be earlier than the "
                        "Assigned Date."))

    @api.depends('asset.asset_code', 'employee.name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = "%s → %s" % (
                rec.asset.asset_code or '',
                rec.employee.name or '')

    @api.depends('returned_date')
    def _compute_is_active(self):
        for rec in self:
            rec.is_active = not rec.returned_date

    @api.constrains('asset', 'returned_date')
    def _check_single_active_assignment(self):
        for rec in self:
            if rec.returned_date:
                continue
            others = self.search([
                ('id', '!=', rec.id),
                ('asset', '=', rec.asset.id),
                ('returned_date', '=', False),
            ])
            if others:
                raise UserError(_(
                    "Asset %s is already assigned to %s. Return it first "
                    "before creating a new assignment."
                ) % (rec.asset.asset_code,
                     others[0].employee.name))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # When a new assignment is created and not yet returned, flip the
        # asset's status to "assigned".
        for rec in records:
            if not rec.returned_date:
                rec.asset.current_status = 'assigned'
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'returned_date' in vals:
            for rec in self:
                if rec.returned_date:
                    # If no other active assignments, free the asset
                    other_active = self.search([
                        ('id', '!=', rec.id),
                        ('asset', '=', rec.asset.id),
                        ('returned_date', '=', False),
                    ], limit=1)
                    if not other_active:
                        rec.asset.current_status = 'available'
                        if rec.return_condition:
                            condition_map = {
                                'good': 'good',
                                'damaged': 'damaged',
                                'missing_parts': 'damaged',
                            }
                            rec.asset.asset_condition = condition_map.get(
                                rec.return_condition,
                                rec.asset.asset_condition)
        return res
