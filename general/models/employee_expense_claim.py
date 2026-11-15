# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError

_CLAIM_PAID_ACTION = object()

class EmployeeExpenseClaim(models.Model):
    _name = "employee.expense.claim"
    _description = "Employee Expense Claim"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "claim_date desc, id desc"
    _rec_name = "claim_number"

    claim_number = fields.Char(
        string="Claim Number", required=True, copy=False,
        readonly=True, default=lambda self: _('New'))
    employee = fields.Many2one(
        'hr.employee', string="Employee", required=True, tracking=True,
        default=lambda self: self.env.user.employee_id)
    department = fields.Many2one(
        'hr.department', string="Department",
        compute='_compute_department', store=True, readonly=False)
    claim_date = fields.Date(
        string="Claim Requested Date", required=True, tracking=True)

    # Period
    expense_period_from = fields.Date(string="Expense Period From")
    expense_period_to = fields.Date(string="Expense Period To")

    # Project/Client
    project_id = fields.Many2one('project.project', string="Project")
    partner_id = fields.Many2one('res.partner', string="Client")

    # Lines
    expense_line_ids = fields.One2many(
        'employee.expense.line', 'expense_claim',
        string="Expense Lines", copy=True)

    # Totals
    total_amount = fields.Monetary(
        string="Total Amount", compute='_compute_total_amount',
        store=True, tracking=True)
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id)
    advance_paid = fields.Monetary(
        string="Advance Paid", currency_field='currency_id',
        default=0.0, tracking=True)
    balance_with_employee = fields.Monetary(
        string="Balance with Employee", currency_field='currency_id',
        compute='_compute_advance_balance', store=True)
    amount_to_be_paid = fields.Monetary(
        string="Amount to Be Paid", currency_field='currency_id',
        compute='_compute_advance_balance', store=True)

    # Status (plain selection — set manually)
    approval_status = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('submitted', 'Submitted'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
            ('paid', 'Paid'),
        ],
        string="Approval Status", required=True, default='draft',
        tracking=True)
    approved_by = fields.Many2one(
        'res.users', string="Approved By")
    approved_date = fields.Date(string="Approved Date")
    approved_amount = fields.Monetary(
        string="Approved Amount", currency_field='currency_id', tracking=True)

    # Payment
    payment_status = fields.Selection(
        selection=[
            ('unpaid', 'Unpaid'),
            ('paid', 'Paid'),
        ],
        string="Payment Status", default='unpaid', tracking=True)
    paid_date = fields.Date(string="Paid Date")

    # Technical, for the Expense Claims list header buttons. Odoo refuses a
    # view whose button `invisible` names something that is not a field in
    # the view, so the two names exist as fields and sit in the list as
    # column_invisible. On a record they say whether THAT claim can be
    # approved / paid; in the list header they are overridden by the summary
    # over the SELECTED rows built by static/src/js/expense_claim_list_header.js
    # (true when at least one selected claim qualifies).
    ft_claim_can_approve = fields.Boolean(
        string="Can Be Approved (technical)", compute='_compute_ft_claim_can')
    ft_claim_can_pay = fields.Boolean(
        string="Can Be Paid (technical)", compute='_compute_ft_claim_can')
    rejection_reason = fields.Text(
        string="Rejection Reason", readonly=True, copy=False, tracking=True,
        help="Why the claim was rejected. A rejected claim stays rejected; "
             "a new claim is raised instead.")
    rejected_by = fields.Many2one(
        'res.users', string="Rejected By", readonly=True, copy=False)
    rejected_date = fields.Date(string="Rejected Date", readonly=True, copy=False)
    payment_reference = fields.Char(string="Payment Reference")
    paid_amount = fields.Monetary(
        string="Paid Amount", currency_field='currency_id', tracking=True)

    remarks = fields.Text(string="Remarks")

    # Advance link. One advance may be adjusted by several claims; a claim
    # draws on one advance. Advance Paid is prefilled with the employee's
    # available advance balance (sum over their open advances) and stays
    # editable; Advance Used is the part of it this claim actually consumes,
    # which the advance sums into its Adjusted Amount.
    advance_id = fields.Many2one(
        'employee.advance', string="Advance Adjusted", index=True,
        domain="[('employee', '=', employee)]",
        help="Advance this claim is adjusted against. Prefilled with the "
             "employee's oldest open advance.")
    advance_used = fields.Monetary(
        string="Advance Used", currency_field='currency_id',
        compute='_compute_advance_used', store=True,
        help="Part of the advance consumed by this claim: the smaller of "
             "Total Amount and Advance Paid. Nothing for a rejected claim.")

    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company)

    _claim_number_uniq = models.Constraint(
        "unique(claim_number, company_id)",
        "Claim number must be unique per company.",
    )
    bill_available = fields.Boolean(string="Bills Available")

    # --------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if (
                vals.get('payment_status') == 'paid'
                or vals.get('approval_status') == 'paid'
            ):
                raise UserError(_(
                    "Create the claim first, then use the Paid button "
                    "to record payment."
                ))
            if vals.get('claim_number', _('New')) == _('New'):
                vals['claim_number'] = self.env[
                    'ir.sequence'].next_by_code(
                    'pms.employee.expense.claim') or _('New')
            if vals.get('employee') and 'advance_paid' not in vals \
                    and not vals.get('advance_id'):
                advances = self._available_advances(
                    vals['employee'], vals.get('company_id') or self.env.company.id)
                if advances:
                    vals['advance_paid'] = sum(advances.mapped('balance_amount'))
                    vals['advance_id'] = advances[0].id
        claims = super().create(vals_list)
        for claim in claims.filtered(lambda c: c.advance_id and c.advance_paid):
            claim.message_post(body=_(
                "Advance Paid prefilled with the available advance balance "
                "%(amount)s (%(advance)s).",
                amount=claim.currency_id.format(claim.advance_paid),
                advance=claim.advance_id.advance_number))
        return claims

    @api.model
    def _available_advances(self, employee_id, company_id):
        """The employee's advances that still hold a balance, oldest first."""
        return self.env['employee.advance'].search([
            ('employee', '=', employee_id),
            ('company_id', '=', company_id),
            ('status', '!=', 'closed'),
            ('balance_amount', '>', 0),
        ], order='advance_date asc, id asc')

    @api.onchange('employee', 'company_id')
    def _onchange_employee_advance(self):
        """On a new claim, Advance Paid starts at the employee's available
        advance balance (editable: add any further advance to it)."""
        for claim in self.filtered(lambda c: not c._origin.id):
            advances = self.env['employee.advance']
            if claim.employee:
                advances = self._available_advances(
                    claim.employee.id, (claim.company_id or self.env.company).id)
            claim.advance_paid = sum(advances.mapped('balance_amount'))
            claim.advance_id = advances[:1]

    @api.depends('total_amount', 'advance_paid', 'approval_status')
    def _compute_advance_used(self):
        for claim in self:
            if claim.approval_status == 'rejected':
                claim.advance_used = 0.0
            else:
                claim.advance_used = min(claim.total_amount or 0.0,
                                         claim.advance_paid or 0.0)

    @api.depends('employee')
    def _compute_department(self):
        for claim in self:
            claim.department = claim.employee.department_id

    @api.depends('expense_line_ids.amount')
    def _compute_total_amount(self):
        for claim in self:
            claim.total_amount = sum(
                line.amount for line in claim.expense_line_ids)

    @api.depends('advance_paid', 'total_amount')
    def _compute_advance_balance(self):
        for claim in self:
            advance = claim.advance_paid or 0.0
            total = claim.total_amount or 0.0
            claim.balance_with_employee = max(advance - total, 0.0)
            claim.amount_to_be_paid = max(total - advance, 0.0)

    @api.constrains('advance_paid')
    def _check_advance_paid(self):
        for rec in self:
            if rec.advance_paid < 0:
                raise UserError(_("Advance Paid cannot be negative."))
                
    @api.constrains('paid_amount')
    def _check_paid_amount(self):
        for rec in self:
            if rec.paid_amount < 0:
                raise UserError(_(
                    "Paid Amount cannot be negative."
                ))

    @api.constrains('expense_period_from', 'expense_period_to')
    def _check_period(self):
        for rec in self:
            if rec.expense_period_from and rec.expense_period_to \
                    and rec.expense_period_from > rec.expense_period_to:
                raise UserError(_(
                    "Expense Period From cannot be after Expense "
                    "Period To."))

    is_approver = fields.Boolean(
        string="Is Approver", compute='_compute_is_approver')

    def _is_manager(self):
        user = self.env.user
        return (self.env.su or self.env.is_admin()
                or user.has_group('general.group_expense_manager')
                or user.has_group('hr.group_hr_user'))

    def _compute_is_approver(self):
        is_manager = self._is_manager()
        for rec in self:
            rec.is_approver = is_manager

    # ---- Status buttons (admin / HR / expense manager only) -----------
    # Approve: not yet approved (a rejected claim is never approved again).
    # Paid: not yet paid (paying an unapproved claim approves it as well).
    # Approved and paid: neither.
    APPROVE_FROM = ('draft', 'submitted')
    PAY_FROM = ('draft', 'submitted', 'approved')

    @api.depends('approval_status', 'payment_status')
    def _compute_ft_claim_can(self):
        for rec in self:
            rec.ft_claim_can_approve = rec.approval_status in self.APPROVE_FROM
            rec.ft_claim_can_pay = (rec.approval_status in self.PAY_FROM
                                    and rec.payment_status != 'paid')

    def _set_claim_status(self, status, allowed_from, bulk=False):
        if not self._is_manager():
            raise UserError(_("Only an Administrator or HR can change the claim status."))
        targets = self.filtered(lambda r: r.approval_status in allowed_from)
        if not bulk and len(targets) != len(self):
            raise UserError(_("This claim cannot be set to '%s' from its current status.", status))
        for rec in targets:
            vals = {'approval_status': status}
            if status == 'approved' and not rec.approved_amount:
                vals['approved_amount'] = rec.total_amount
            if status == 'paid':
                if not rec.approved_amount:
                    vals['approved_amount'] = rec.total_amount
                if not rec.paid_amount:
                    vals['paid_amount'] = rec.amount_to_be_paid
            if status == 'paid':
                rec.with_context(
                    _claim_paid_action=_CLAIM_PAID_ACTION
                ).write(vals)
            else:
                rec.write(vals)
        return True

    def action_approve(self):
        return self._set_claim_status('approved', self.APPROVE_FROM)

    def action_reject(self):
        """Open the rejection wizard: a reason is required."""
        self.ensure_one()
        if not self._is_manager():
            raise UserError(_("Only an Administrator or HR can change the claim status."))
        if self.approval_status not in ('draft', 'submitted', 'approved'):
            raise UserError(_("This claim cannot be rejected from its current status."))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Reject Claim"),
            'res_model': 'employee.expense.claim.reject',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_claim_id': self.id},
        }

    def action_do_reject(self, reason):
        """Reject with the reason; called by the wizard."""
        self._set_claim_status('rejected', ('draft', 'submitted', 'approved'))
        self.write({
            'rejection_reason': reason,
            'rejected_by': self.env.user.id,
            'rejected_date': fields.Date.context_today(self),
        })
        for rec in self:
            rec.message_post(body=_("Claim rejected. Reason: %s", reason))
        return True

    def action_paid(self):
        return self._set_claim_status('paid', self.PAY_FROM)

    def action_bulk_approve(self):
        return self._set_claim_status('approved', self.APPROVE_FROM, bulk=True)

    def action_bulk_paid(self):
        return self._set_claim_status('paid', self.PAY_FROM, bulk=True)

    def action_submit(self):
        for rec in self:
            if rec.approval_status != 'draft':
                raise UserError(_("This claim has already been submitted and cannot be re-submitted."))
            if not rec.expense_line_ids:
                raise UserError(_("Please add at least one expense line before submitting."))
            rec.approval_status = 'submitted'
        return True

    def _check_paid_claim_locked(self):
        if any(
            rec.payment_status == 'paid'
            or rec.approval_status == 'paid'
            for rec in self
        ):
            raise UserError(_(
                "This claim is already paid. "
                "Expense lines and amounts cannot be changed."
            ))
    def write(self, vals):    
        locked_fields = {
            'expense_line_ids',
            'advance_paid',
            'advance_id',
            'advance_used',
            'total_amount',
            'balance_with_employee',
            'amount_to_be_paid',
            'approved_amount',
            'paid_amount',
            'paid_date',
            'currency_id',
            'company_id',
            'employee',
            'approval_status',
            'payment_status',
        }

        if locked_fields.intersection(vals):
            self._check_paid_claim_locked()

        paid_action = (
            self.env.context.get('_claim_paid_action')
            is _CLAIM_PAID_ACTION
        )

        if 'payment_status' in vals:
            raise UserError(_(
                "Payment Status is read-only. Use the Paid button "
                "or Bulk Paid action."
            ))

        if vals.get('approval_status') == 'paid' and not paid_action:
            raise UserError(_(
                "Use the Paid button or Bulk Paid action "
                "to mark this claim as paid."
            ))

        is_manager = self._is_manager()
        if not is_manager:
            for rec in self:
                if rec.approval_status != 'draft':
                    raise UserError(_(
                        "You cannot modify an expense claim "
                        "that has already been submitted."
                    ))
                if (
                    'approval_status' in vals
                    and vals['approval_status'] not in ('draft', 'submitted')
                ):
                    raise UserError(_(
                        "Only an approver can approve, reject, "
                        "or mark an expense claim as paid."
                    ))

        if 'approval_status' not in vals:
            return super().write(vals)

        status = vals['approval_status']
        for rec in self:
            rec_vals = dict(vals)
            today = fields.Date.context_today(rec)

            if status == 'approved':
                rec_vals.setdefault(
                    'approved_by', rec.approved_by.id or self.env.user.id
                )
                rec_vals.setdefault(
                    'approved_date', rec.approved_date or today
                )

            elif status == 'paid':
                rec_vals.setdefault('payment_status', 'paid')
                rec_vals.setdefault(
                    'approved_by', rec.approved_by.id or self.env.user.id
                )
                rec_vals.setdefault(
                    'approved_date', rec.approved_date or today
                )
                rec_vals.setdefault('paid_date', rec.paid_date or today)

            elif status == 'rejected':
                rec_vals.setdefault('payment_status', 'unpaid')
                rec_vals.setdefault(
                    'rejected_by', rec.rejected_by.id or self.env.user.id
                )
                rec_vals.setdefault(
                    'rejected_date', rec.rejected_date or today
                )

            elif status in ('draft', 'submitted'):
                rec_vals.setdefault('payment_status', 'unpaid')

            super(EmployeeExpenseClaim, rec).write(rec_vals)

        return True

    def unlink(self):
        self._check_paid_claim_locked()
        is_manager = self._is_manager()
        if not is_manager:
            for rec in self:
                if rec.approval_status != 'draft':
                    raise UserError(_(
                        "You cannot delete an expense claim that has already been submitted."
                    ))
        return super().unlink()