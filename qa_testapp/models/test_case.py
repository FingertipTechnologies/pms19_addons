from odoo import models, fields, api
from odoo.exceptions import UserError


class QATestCase(models.Model):
    _name = 'qa_testapp.test_case'
    _description = 'QA Test Case'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'test_case_id'

    test_case_id = fields.Char(string='Test Case ID', readonly=True, copy=False, default='New')
    url_ids = fields.One2many(
        'qa_testapp.resource_url', 'test_case_id', string='URLs')
    test_case_title = fields.Char(string='Test Case Title', required=True, tracking=True)
    project_id = fields.Many2one('project.project', string='Project', required=True, tracking=True)
    module_id = fields.Many2one(
        'cus.module', string='Module', required=True,
        domain="[('id', 'in', available_module_ids)]",
    )
    available_module_ids = fields.Many2many(
        'cus.module', compute='_compute_available_modules',
    )
    test_objective = fields.Text(string='Test Details')
    pre_conditions = fields.Text(string='Pre Conditions')
    test_data = fields.Text(string='Test Data')
    test_steps = fields.Text(string='Test Steps')
    expected_result = fields.Text(string='Expected Result')
    actual_result = fields.Text(string='Actual Result')
    status = fields.Selection([
        ('pass', 'Pass'),
        ('fail', 'Fail'),
        ('blocked', 'Blocked'),
        ('not_executed', 'Not Executed')
    ], string='Status', default='not_executed', tracking=True)
    severity = fields.Selection([
        ('critical', 'Critical'),
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low')
    ], string='Severity', default='medium')
    environment = fields.Selection([
        ('sandbox', 'Sandbox'),
        ('qa', 'QA'),
        ('production', 'Production')
    ], string='Environment', default='sandbox')
    executed_date = fields.Date(string='Executed Date')
    executed_by = fields.Many2one('res.users', string='Executed By')
    test_type = fields.Selection([
        ('smoke', 'Smoke'),
        ('functional', 'Functional'),
        ('uat', 'UAT'),
        ('regression', 'Regression')
    ], string='Test Type', default='smoke')

    approval_state = fields.Selection([
        ('pending_approval', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], string='Approval State', default='approved', tracking=True, copy=False,
       help="Junior QA submissions start as Pending Approval. PM of the project approves or rejects. "
            "Execution status can only be changed once approved.")
    approver_id = fields.Many2one(
        'res.users', string='Approver (Project PM)',
        compute='_compute_approver_id', store=True, readonly=True,
    )
    rejection_reason = fields.Text(string='Rejection Reason', copy=False, readonly=True)
    is_current_user_approver = fields.Boolean(
        string='Current User Is Approver',
        compute='_compute_is_current_user_approver',
    )
    is_creator = fields.Boolean(
        string='Current User Is Creator',
        compute='_compute_is_creator',
    )
    creator_unlocked = fields.Boolean(
        string='Unlocked by Creator', default=False, copy=False,
        help="Set when the creator clicks Edit to change a record that is "
             "still pending approval. Only the creator can unlock it.",
    )

    @api.depends('project_id', 'project_id.user_id')
    def _compute_approver_id(self):
        for rec in self:
            rec.approver_id = rec.project_id.user_id

    @api.depends('approver_id')
    def _compute_is_current_user_approver(self):
        for rec in self:
            rec.is_current_user_approver = rec.approver_id == self.env.user

    @api.depends_context('uid')
    def _compute_is_creator(self):
        for rec in self:
            rec.is_creator = bool(rec.create_uid) and rec.create_uid.id == self.env.uid

    @api.depends('project_id')
    def _compute_available_modules(self):
        for rec in self:
            if rec.project_id:
                tasks = self.env['project.task'].sudo().search([
                    ('project_id', '=', rec.project_id.id),
                    ('module_id', '!=', False),
                ])
                rec.available_module_ids = tasks.mapped('module_id')
            else:
                rec.available_module_ids = self.env['cus.module'].sudo().search([])

    @api.onchange('project_id')
    def _onchange_project_id(self):
        self.module_id = False

    @api.model
    def _is_junior_qa(self, user=None):
        user = user or self.env.user
        return user.has_group('qa_testapp.group_qa_junior')

    @api.model_create_multi
    def create(self, vals_list):
        junior = self._is_junior_qa()
        for vals in vals_list:
            if vals.get('test_case_id', 'New') == 'New':
                vals['test_case_id'] = self.env['ir.sequence'].next_by_code(
                    'qa_testapp.test_case'
                ) or 'New'
            if junior:
                vals['approval_state'] = 'pending_approval'
        records = super().create(vals_list)
        # Junior-QA test cases sit in 'pending_approval' for the PM to review
        # from the Test Cases list - no approval email is sent.
        return records

    def write(self, vals):
        EXECUTION_FIELDS = {'status', 'executed_date', 'executed_by', 'actual_result'}
        if vals.keys() & EXECUTION_FIELDS:
            for rec in self:
                if rec.approval_state == 'pending_approval':
                    raise UserError(
                        "Test Case %s is pending approval. The PM must approve it before execution." % (rec.test_case_id or '',)
                    )
                if rec.approval_state == 'rejected':
                    raise UserError(
                        "Test Case %s has been rejected. Execution fields cannot change." % (rec.test_case_id or '',)
                    )
        return super().write(vals)

    def action_creator_edit(self):
        """Unlock a still-pending test case so its creator can edit it.
        Only the record's creator may unlock it."""
        self.ensure_one()
        if not self.is_creator:
            raise UserError(
                "Only the creator can edit test case %s while it is pending approval." % (self.test_case_id or '',)
            )
        self.creator_unlocked = True

    def action_approve(self):
        for rec in self:
            if rec.approval_state != 'pending_approval':
                continue
            if rec.approver_id and rec.approver_id != self.env.user and not self.env.user.has_group('base.group_system'):
                raise UserError(
                    "Only %s (PM of project '%s') can approve test case %s." % (
                        rec.approver_id.name, rec.project_id.name, rec.test_case_id,
                    )
                )
            rec.approval_state = 'approved'
            rec.message_post(body="Test case approved by %s." % self.env.user.name)
            rec._notify_approval()

    def action_reject(self, reason=None):
        for rec in self:
            if rec.approval_state != 'pending_approval':
                continue
            if rec.approver_id and rec.approver_id != self.env.user and not self.env.user.has_group('base.group_system'):
                raise UserError(
                    "Only %s (PM of project '%s') can reject test case %s." % (
                        rec.approver_id.name, rec.project_id.name, rec.test_case_id,
                    )
                )
            rec.approval_state = 'rejected'
            if reason:
                rec.rejection_reason = reason
            rec.message_post(body="Test case rejected by %s. Reason: %s" % (self.env.user.name, reason or '(none)'))
            rec._notify_rejection()

    def action_reject_open_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Reject Test Case',
            'res_model': 'qa_testapp.bulk_approve_wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': 'qa_testapp.test_case',
                'active_ids': self.ids,
                'default_action_type': 'reject',
            },
        }

    def _notify_pending_approval(self):
        self.ensure_one()
        if self.approver_id and self.approver_id.email:
            template = self.env.ref('qa_testapp.email_template_test_case_pending_approval', raise_if_not_found=False)
            if template:
                template.sudo().send_mail(self.id, force_send=True)

    def _notify_approval(self):
        self.ensure_one()
        if self.create_uid and self.create_uid.email:
            template = self.env.ref('qa_testapp.email_template_test_case_approved', raise_if_not_found=False)
            if template:
                template.sudo().send_mail(self.id, force_send=True)

    def _notify_rejection(self):
        self.ensure_one()
        if self.create_uid and self.create_uid.email:
            template = self.env.ref('qa_testapp.email_template_test_case_rejected', raise_if_not_found=False)
            if template:
                template.sudo().send_mail(self.id, force_send=True)
