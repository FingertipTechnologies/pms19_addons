# -*- coding: utf-8 -*-
from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_COMP_OFF_TRANSITION = object()


class EmployeeCompOff(models.Model):
    _name = "employee.comp.off"
    _description = "Employee Comp-Off"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "work_date desc, id desc"
    _rec_name = "display_name"

    _APPROVER_ONLY_FIELDS = {
        'eligibility', 'approved_by',
        'rejection_reason', 'rejected_by', 'rejected_date',
    }
    _HR_ONLY_FIELDS = {'availed_date', 'status'}

    display_name = fields.Char(
        compute='_compute_display_name', store=True)

    employee_id = fields.Many2one(
        'hr.employee', string="Employee Name", required=True, tracking=True,
        default=lambda self: self.env.user.employee_id)
    work_date = fields.Date(
        string="Work Date", required=True, tracking=True)
    project_id = fields.Many2one(
        'project.project', string="Project", required=True, tracking=True)
    hours_worked = fields.Float(
        string="Hours Worked", required=True, tracking=True)
    timesheet_hours = fields.Float(
        string="Timesheet Entered Hours", compute='_compute_timesheet_hours',
        readonly=True)
    tracked_in_tymake = fields.Selection(
        selection=[
            ('yes', 'Yes'),
            ('no', 'No'),
        ],
        string="Tracked in Tymake?", required=True, default='no',
        tracking=True)
    purpose = fields.Text(
        string="Purpose of Out-of-Office Work", required=True, tracking=True)
    work_description = fields.Text(
        string="Work Description", required=True)

    approved_by = fields.Many2one(
        'res.users', string="Approved By", readonly=True, copy=False,
        tracking=True)
    eligibility = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('pending', 'Pending'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
        ],
        string="Comp-Off Eligibility", required=True, default='draft',
        copy=False, tracking=True)
    rejection_reason = fields.Text(
        string="Rejection Reason", readonly=True, copy=False, tracking=True)
    rejected_by = fields.Many2one(
        'res.users', string="Rejected By", readonly=True, copy=False,
        tracking=True)
    rejected_date = fields.Date(
        string="Rejected Date", readonly=True, copy=False)

    availed_date = fields.Date(
        string="Comp-Off Date Availed", copy=False, tracking=True)
    status = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('availed', 'Availed'),
            ('expired', 'Expired'),
        ],
        string="Status", copy=False, tracking=True)

    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company)
    is_hr_approver = fields.Boolean(
        string="Is HR/Admin Approver", compute='_compute_role_flags')
    is_hr_officer = fields.Boolean(
        string="Is HR Officer", compute='_compute_role_flags')

    @api.depends('employee_id.name', 'work_date')
    def _compute_display_name(self):
        for rec in self:
            parts = [
                part for part in (
                    rec.employee_id.name,
                    str(rec.work_date) if rec.work_date else '',
                ) if part
            ]
            rec.display_name = " - ".join(parts) if parts else _("Comp-Off")

    @api.depends('employee_id', 'work_date')
    def _compute_timesheet_hours(self):
        valid = self.filtered(
            lambda r: isinstance(r.employee_id.id, int) and r.work_date
        )
        for rec in self - valid:
            rec.timesheet_hours = 0.0
        if not valid:
            return
        emp_ids = list({rec.employee_id.id for rec in valid})
        dates = list({rec.work_date for rec in valid})
        grouped = self.env['account.analytic.line'].sudo()._read_group(
            [
                ('employee_id', 'in', emp_ids),
                ('date', 'in', dates),
                ('project_id', '!=', False),
            ],
            ['employee_id', 'date:day'],
            ['unit_amount:sum'],
        )
        hours_map = {}
        for emp, day, total in grouped:
            if emp and day:
                day_val = day.date() if isinstance(day, datetime) else day
                hours_map[(emp.id, day_val)] = total or 0.0
        for rec in valid:
            rec.timesheet_hours = hours_map.get(
                (rec.employee_id.id, rec.work_date), 0.0
            )

    def _is_hr_approver(self):
        user = self.env.user
        return (
            self.env.su
            or self.env.is_admin()
            or user.has_group('hr.group_hr_user')
            or user.has_group('base.group_system')
        )

    def _is_hr_officer(self):
        return self.env.su or self.env.user.has_group('hr.group_hr_user')

    def _own_employee(self):
        employee = self.env.user.employee_id
        if not employee:
            raise UserError(_(
                "Your user account is not linked to an Employee record. "
                "Please contact HR."
            ))
        return employee

    def _compute_role_flags(self):
        is_approver = self._is_hr_approver()
        is_hr = self._is_hr_officer()
        for rec in self:
            rec.is_hr_approver = is_approver
            rec.is_hr_officer = is_hr

    @api.onchange('availed_date')
    def _onchange_availed_date(self):
        if (
            self.availed_date
            and self.eligibility == 'approved'
            and self.status in (False, 'pending')
        ):
            self.status = 'availed'

    @api.constrains('hours_worked')
    def _check_hours_worked(self):
        for rec in self:
            if rec.hours_worked <= 0:
                raise ValidationError(_("Hours Worked must be greater than zero."))

    @api.constrains('work_date')
    def _check_work_date_not_future(self):
        for rec in self:
            today = fields.Date.context_today(rec)
            if rec.work_date and rec.work_date > today:
                raise ValidationError(_("Work Date cannot be a future date."))

    @api.constrains('employee_id', 'work_date', 'eligibility')
    def _check_unique_request_per_day(self):
        elig_labels = dict(self._fields['eligibility'].selection)
        for rec in self:
            if rec.eligibility == 'rejected' or not rec.employee_id or not rec.work_date:
                continue
            duplicate = self.sudo().search([
                ('id', '!=', rec.id),
                ('employee_id', '=', rec.employee_id.id),
                ('work_date', '=', rec.work_date),
                ('eligibility', '!=', 'rejected'),
            ], limit=1)
            if duplicate:
                state_label = elig_labels.get(duplicate.eligibility, duplicate.eligibility)
                raise ValidationError(_(
                    "A Comp-Off request for %(employee)s on %(date)s already exists "
                    "(%(state)s). Only one request per day is allowed unless the "
                    "previous request was rejected.",
                    employee=rec.employee_id.name,
                    date=rec.work_date,
                    state=state_label,
                ))

    @api.constrains('eligibility', 'availed_date', 'status', 'work_date')
    def _check_availment_rules(self):
        for rec in self:
            if (rec.availed_date or rec.status) and rec.eligibility != 'approved':
                raise ValidationError(_(
                    "Comp-Off Date Availed and Status can only be set once "
                    "Comp-Off Eligibility is Approved."
                ))
            if rec.availed_date and rec.work_date and rec.availed_date <= rec.work_date:
                raise ValidationError(_(
                    "Comp-Off Date Availed must be after Work Date."
                ))

    @api.model_create_multi
    def create(self, vals_list):
        is_approver = self._is_hr_approver()
        is_hr = self._is_hr_officer()
        own_employee = None if self.env.su else self._own_employee()
        for vals in vals_list:
            if own_employee:
                if vals.get('employee_id') and vals['employee_id'] != own_employee.id:
                    raise UserError(_(
                        "You can only apply Comp-Off for yourself, not for another employee."
                    ))
                vals['employee_id'] = own_employee.id
            if not is_approver:
                if (
                    vals.get('eligibility', 'draft') != 'draft'
                    or vals.get('approved_by')
                    or vals.get('rejection_reason')
                    or vals.get('rejected_by')
                    or vals.get('rejected_date')
                ):
                    raise UserError(_(
                        "Only HR / Admin can approve or reject Comp-Off requests."
                    ))
            if not is_hr and (vals.get('availed_date') or vals.get('status')):
                raise UserError(_(
                    "Only HR can set Comp-Off Date Availed or Status."
                ))
            if vals.get('eligibility') == 'rejected' and not vals.get('rejection_reason'):
                raise UserError(_(
                    "Please provide a rejection reason when rejecting Comp-Off."
                ))
            if vals.get('eligibility') == 'approved':
                vals.setdefault('approved_by', self.env.user.id)
                vals.setdefault('status', 'pending')
        return super().create(vals_list)

    def write(self, vals):
        is_transition = (
            self.env.context.get('_comp_off_transition') is _COMP_OFF_TRANSITION
        )
        if not self.env.su and 'employee_id' in vals:
            if any(rec.employee_id.id != vals['employee_id'] for rec in self):
                raise UserError(_(
                    "You can only apply Comp-Off for yourself, not for another employee."
                ))
        if (
            not is_transition
            and not self._is_hr_approver()
            and (self._APPROVER_ONLY_FIELDS & vals.keys())
        ):
            raise UserError(_(
                "Only HR / Admin can update Comp-Off approval or rejection."
            ))
        if (
            not is_transition
            and not self._is_hr_officer()
            and (self._HR_ONLY_FIELDS & vals.keys())
        ):
            raise UserError(_(
                "Only HR can update Comp-Off Date Availed or Status."
            ))

        vals_to_write = dict(vals)
        if 'eligibility' in vals_to_write:
            new_elig = vals_to_write['eligibility']
            if new_elig == 'approved':
                vals_to_write.setdefault('approved_by', self.env.user.id)
                vals_to_write.setdefault('status', 'pending')
                vals_to_write.setdefault('rejection_reason', False)
                vals_to_write.setdefault('rejected_by', False)
                vals_to_write.setdefault('rejected_date', False)
            elif new_elig == 'rejected':
                if not is_transition and not vals_to_write.get('rejection_reason'):
                    raise UserError(_(
                        "Please use the Reject button to provide a rejection reason."
                    ))
                vals_to_write.setdefault('approved_by', False)
                vals_to_write.setdefault('availed_date', False)
                vals_to_write.setdefault('status', False)
            else:
                vals_to_write.setdefault('approved_by', False)
                vals_to_write.setdefault('availed_date', False)
                vals_to_write.setdefault('status', False)
                vals_to_write.setdefault('rejection_reason', False)
                vals_to_write.setdefault('rejected_by', False)
                vals_to_write.setdefault('rejected_date', False)

        return super().write(vals_to_write)

    def _ensure_hr_approver(self):
        if not self._is_hr_approver():
            raise UserError(_(
                "Only HR / Admin can approve or reject Comp-Off requests."
            ))

    def action_submit(self):
        if any(rec.eligibility != 'draft' for rec in self):
            raise UserError(_(
                "Only draft Comp-Off requests can be submitted."
            ))
        self.with_context(_comp_off_transition=_COMP_OFF_TRANSITION).write({
            'eligibility': 'pending',
        })
        return True

    def action_approve(self):
        self._ensure_hr_approver()
        if any(rec.eligibility != 'pending' for rec in self):
            raise UserError(_("Only pending Comp-Off requests can be approved."))
        self.with_context(_comp_off_transition=_COMP_OFF_TRANSITION).write({
            'eligibility': 'approved',
            'approved_by': self.env.user.id,
            'status': 'pending',
            'rejection_reason': False,
            'rejected_by': False,
            'rejected_date': False,
        })

    def action_reject(self):
        """Open the rejection wizard so HR / Admin must enter a reason."""
        self.ensure_one()
        self._ensure_hr_approver()
        if self.eligibility != 'pending':
            raise UserError(_("Only pending Comp-Off requests can be rejected."))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Reject Comp-Off"),
            'res_model': 'employee.comp.off.reject',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_comp_off_id': self.id},
        }

    def action_do_reject(self, reason):
        """Store rejection reason and mark Comp-Off eligibility as rejected."""
        self._ensure_hr_approver()
        self.with_context(_comp_off_transition=_COMP_OFF_TRANSITION).write({
            'eligibility': 'rejected',
            'rejection_reason': reason,
            'rejected_by': self.env.user.id,
            'rejected_date': fields.Date.context_today(self),
            'approved_by': False,
            'availed_date': False,
            'status': False,
        })
        return True
