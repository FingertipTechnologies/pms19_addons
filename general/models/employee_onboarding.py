# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class EmployeeOnboarding(models.Model):
    _name = "employee.onboarding"
    _description = "Employee Onboarding"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "joining_date desc, id desc"
    _rec_name = "name"

    name = fields.Char(
        string="Reference", compute="_compute_name",
        store=True, readonly=True)

    candidate = fields.Many2one(
        'recruitment.candidate', string="Candidate", required=True,
        tracking=True, ondelete='restrict')
    employee_created = fields.Boolean(
        string="Employee Created", default=False, readonly=True,
        tracking=True)
    employee_id = fields.Many2one(
        'hr.employee', string="Linked Employee", readonly=True)
    joining_date = fields.Date(
        string="Joining Date", required=True, tracking=True)
    department = fields.Many2one('hr.department', string="Department")
    reporting_manager = fields.Many2one(
        'hr.employee', string="Reporting Manager")

    # Checklist
    asset_required = fields.Boolean(string="Asset Required")
    laptop_required = fields.Boolean(string="Laptop Required")
    email_created = fields.Boolean(string="Email Created")
    documents_collected = fields.Boolean(string="Documents Collected")
    offer_letter_signed = fields.Boolean(string="Offer Letter Signed")
    nda_signed = fields.Boolean(string="NDA Signed")

    status = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('in_progress', 'In Progress'),
            ('completed', 'Completed'),
        ],
        string="Status", required=True, default='pending', tracking=True)

    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company)

    @api.depends('candidate', 'candidate.candidate_name')
    def _compute_name(self):
        for rec in self:
            if rec.candidate and rec.candidate.candidate_name:
                rec.name = "Onboarding — %s" % rec.candidate.candidate_name
            else:
                rec.name = "Onboarding"

    def action_create_employee(self):
        """Create an hr.employee from the candidate's details."""
        for rec in self:
            if rec.employee_created:
                raise UserError(_(
                    "An employee has already been created for this "
                    "onboarding record."))
            if not rec.candidate:
                raise UserError(_("Please link a candidate first."))
            employee = self.env['hr.employee'].create({
                'name': rec.candidate.candidate_name,
                'work_email': rec.candidate.email or False,
                'mobile_phone': rec.candidate.mobile_number or False,
                'department_id': rec.department.id or False,
                'parent_id': rec.reporting_manager.id or False,
                'job_title': rec.candidate.applied_position.job_title
                or False,
            })
            rec.employee_id = employee.id
            rec.employee_created = True
            rec.candidate.candidate_status = 'joined'
        return True

    def write(self, vals):
        res = super().write(vals)
        if vals.get('status') == 'completed':
            for rec in self:
                if not rec.employee_created:
                    rec.action_create_employee()
        return res