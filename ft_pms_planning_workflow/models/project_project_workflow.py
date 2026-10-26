# -*- coding: utf-8 -*-
"""Stage workflow for Implementation projects.

Stage gates (evidence / sign-off / approval required to move FORWARD), the
REG sign-off owned by QA, the Finance payment clearances, the Admin approval
for UAT and the stage-change e-mail notifications. The project lock lives in
``project_project_lock.py``.

Everything here is enforced in ``project.project.write`` so the Kanban drag,
the form status bar, imports and RPC all obey the same rules. Like the
existing Stage Validation Framework of bt_project_customization the gates are
skipped under ``env.su`` (migrations, server actions, crons).
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.fields import Command
from odoo.tools import format_datetime, is_html_empty
from odoo.tools.mail import email_normalize

from odoo.addons.bt_project_customization.models.project_project import PM_JOB_NAMES
from odoo.addons.bt_project_customization.models.project_task import TESTER_JOB_NAMES

_logger = logging.getLogger(__name__)

# REG sign-off fields: writable only by QA (tester job / QA group) or admin.
PWF_REG_FIELDS = (
    'pwf_reg_current_status',
    'pwf_reg_open_issues',
    'pwf_reg_signoff_details',
    'pwf_reg_signed_by_id',
    'pwf_reg_signed_on',
)
# Stage keys carrying a Finance payment clearance (pwf_fin_clear_<key>).
PWF_FIN_KEYS = ('dev', 'uat', 'data', 'support', 'closed')
PWF_FIN_FLAG_FIELDS = tuple('pwf_fin_clear_%s' % key for key in PWF_FIN_KEYS)
# Finance clearance fields: writable only by Finance (group_pms_finance).
PWF_FIN_FIELDS = tuple(
    fname
    for key in PWF_FIN_KEYS
    for fname in ('pwf_fin_clear_%s' % key,
                  'pwf_fin_clear_%s_by_id' % key,
                  'pwf_fin_clear_%s_on' % key)
)
PWF_FINANCE_GROUP = 'ft_pms_planning_workflow.group_pms_finance'
# Stage descriptions for the stage-change e-mail, by stage key.
PWF_STAGE_DESCRIPTIONS = {
    'disc': 'Discovery',
    'dev': 'Development',
    'reg': 'Regression',
    'srv': 'Sandbox Review',
    'uat': 'User Acceptance Testing',
    'data': 'Data Upload',
    'tra': 'Training',
    'support': 'Support',
    'closed': 'Closed',
    'hold': 'On Hold',
}
PWF_MOVED_ON_FORMAT = 'd MMM yyyy, h:mm a'
# Stage-change e-mails always go out from the support mailbox, whoever moves
# the stage (same sender as ft_helpdesk_ticket_emails).
PWF_STAGE_EMAIL_FROM = 'Support Fingertip <support@fingertipplus.com>'
PWF_STAGE_REPLY_TO = 'support@fingertipplus.com'
# Stage keys (see project.project.stage._ft_stage_key) that carry a gate.
PWF_GATED_KEYS = ('dev', 'srv', 'uat', 'data', 'tra', 'support', 'closed')
# Gates whose evidence must be present for DATA and every later stage.
PWF_POST_UAT_KEYS = ('data', 'tra', 'support', 'closed')


def _pwf_job_names(user):
    """Lower-cased job names of every (active) employee linked to ``user``."""
    if not user:
        return set()
    employees = user.env['hr.employee'].sudo().search([('user_id', '=', user.id)])
    return {(emp.job_id.name or '').strip().lower() for emp in employees if emp.job_id}


class ProjectProject(models.Model):
    _inherit = 'project.project'

    # ------------------------------------------------------------------
    # Evidence / sign-off fields
    # ------------------------------------------------------------------
    pwf_brd_signoff_attachment_ids = fields.Many2many(
        'ir.attachment', 'pwf_project_brd_signoff_attachment_rel',
        'project_id', 'attachment_id',
        string='Signed BRD Evidence', copy=False,
        help='Screenshot of the client e-mail signing off the BRD. Required '
             'before the project can enter DEV.',
    )
    # REG sign-off (gate of SRV), owned by QA.
    pwf_reg_current_status = fields.Html(
        string='REG Current Status', copy=False)
    pwf_reg_open_issues = fields.Html(
        string='REG Open Issues', copy=False)
    pwf_reg_signoff_details = fields.Html(
        string='REG Sign-off Details', copy=False)
    pwf_reg_signed_by_id = fields.Many2one(
        'res.users', string='REG Signed Off By', copy=False, tracking=True)
    pwf_reg_signed_on = fields.Datetime(
        string='REG Signed Off On', copy=False, tracking=True)
    pwf_can_edit_reg = fields.Boolean(
        string='Can Edit REG Sign-off', compute='_compute_pwf_can_edit_reg')

    # UAT gate
    pwf_sandbox_review_attachment_ids = fields.Many2many(
        'ir.attachment', 'pwf_project_sandbox_review_attachment_rel',
        'project_id', 'attachment_id',
        string='Sandbox Review Evidence', copy=False,
        help='Evidence of the client sandbox review. Required, together with '
             'an Admin approval, before the project can enter UAT.',
    )
    pwf_approval_ids = fields.One2many(
        'ft.pms.stage.approval', 'project_id', string='Stage Approvals')
    pwf_pending_approval_id = fields.Many2one(
        'ft.pms.stage.approval', string='Pending Approval',
        compute='_compute_pwf_approval_state')
    pwf_can_request_uat_approval = fields.Boolean(
        compute='_compute_pwf_approval_state')
    # Status of the latest UAT approval request (any requester).
    pwf_uat_request_state = fields.Selection([
        ('none', 'Not requested'),
        ('pending', 'Requested'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ], string='UAT Request Status', compute='_compute_pwf_uat_request',
        compute_sudo=True)
    pwf_uat_request_date = fields.Datetime(
        string='UAT Requested On', compute='_compute_pwf_uat_request',
        compute_sudo=True)
    pwf_uat_request_decided_by_id = fields.Many2one(
        'res.users', string='UAT Request Decided By',
        compute='_compute_pwf_uat_request', compute_sudo=True)
    pwf_uat_request_reason = fields.Text(
        string='UAT Rejection Reason', compute='_compute_pwf_uat_request',
        compute_sudo=True)

    # DATA and later
    pwf_uat_signoff_attachment_ids = fields.Many2many(
        'ir.attachment', 'pwf_project_uat_signoff_attachment_rel',
        'project_id', 'attachment_id',
        string='Customer UAT Sign-off / Completion E-mail Screenshot',
        copy=False,
        help='Screenshot of the customer\'s UAT sign-off / UAT completion '
             'e-mail. Required before DATA and every later stage.',
    )
    # Legacy: merged into pwf_uat_signoff_attachment_ids (same evidence).
    # Kept so existing attachments are not lost; no gate requires it.
    pwf_uat_completion_attachment_ids = fields.Many2many(
        'ir.attachment', 'pwf_project_uat_completion_attachment_rel',
        'project_id', 'attachment_id',
        string='UAT Completion Evidence (legacy)', copy=False,
        help='Legacy field, no longer required: the Customer UAT Sign-off / '
             'Completion E-mail Screenshot covers it.',
    )
    # CLOSED
    pwf_internal_feedback_attachment_ids = fields.Many2many(
        'ir.attachment', 'pwf_project_internal_feedback_attachment_rel',
        'project_id', 'attachment_id',
        string='Internal Feedback Screenshot', copy=False,
        help='Screenshot confirming that the internal project feedback has '
             'been submitted. Required before CLOSED.',
    )
    # Legacy feedback links: kept for history, no longer used by the gates.
    pwf_feedback_response_id = fields.Many2one(
        'ft.feedback.response', string='Internal Feedback', copy=False,
        domain="[('project_id', '=', id), ('submission_token', '=', False)]",
        help='Legacy link to the internal feedback response (not required).',
    )
    pwf_portal_feedback_response_id = fields.Many2one(
        'ft.feedback.response', string='Portal Feedback', copy=False,
        domain="[('project_id', '=', id), ('submission_token', '!=', False)]",
        help='Legacy link to the portal feedback response (not required).',
    )
    pwf_external_feedback_attachment_ids = fields.Many2many(
        'ir.attachment', 'pwf_project_external_feedback_attachment_rel',
        'project_id', 'attachment_id',
        string='External Review Screenshot', copy=False,
        help='Screenshot confirming that the external review has been '
             'submitted through the Partner Portal. Required before CLOSED.',
    )
    pwf_google_review_attachment_ids = fields.Many2many(
        'ir.attachment', 'pwf_project_google_review_attachment_rel',
        'project_id', 'attachment_id',
        string='Google Review Evidence', copy=False,
    )
    pwf_retro_went_well = fields.Html(string='What Went Well', copy=False)
    pwf_retro_went_wrong = fields.Html(string='What Went Wrong', copy=False)
    pwf_retro_to_correct = fields.Html(
        string='What Needs to Be Corrected', copy=False)

    # Finance payment clearance, one set per gated stage (PWF_FIN_KEYS).
    pwf_fin_clear_dev = fields.Boolean(
        string='Finance Payment Clearance', copy=False, tracking=True,
        help='Finance confirms the payment due before DEV has been received.')
    pwf_fin_clear_dev_by_id = fields.Many2one(
        'res.users', string='DEV Clearance By', readonly=True, copy=False)
    pwf_fin_clear_dev_on = fields.Datetime(
        string='DEV Clearance On', readonly=True, copy=False)
    pwf_fin_clear_uat = fields.Boolean(
        string='Finance Payment Clearance', copy=False, tracking=True,
        help='Finance confirms the payment due before UAT has been received.')
    pwf_fin_clear_uat_by_id = fields.Many2one(
        'res.users', string='UAT Clearance By', readonly=True, copy=False)
    pwf_fin_clear_uat_on = fields.Datetime(
        string='UAT Clearance On', readonly=True, copy=False)
    pwf_fin_clear_data = fields.Boolean(
        string='Finance Payment Clearance', copy=False, tracking=True,
        help='Finance confirms the payment due before DATA has been received.')
    pwf_fin_clear_data_by_id = fields.Many2one(
        'res.users', string='DATA Clearance By', readonly=True, copy=False)
    pwf_fin_clear_data_on = fields.Datetime(
        string='DATA Clearance On', readonly=True, copy=False)
    pwf_fin_clear_support = fields.Boolean(
        string='Finance Payment Clearance', copy=False, tracking=True,
        help='Finance confirms the payment due before SUPPORT has been received.')
    pwf_fin_clear_support_by_id = fields.Many2one(
        'res.users', string='SUPPORT Clearance By', readonly=True, copy=False)
    pwf_fin_clear_support_on = fields.Datetime(
        string='SUPPORT Clearance On', readonly=True, copy=False)
    pwf_fin_clear_closed = fields.Boolean(
        string='Finance Payment Clearance', copy=False, tracking=True,
        help='Finance confirms the final payment has been received before '
             'the project is CLOSED.')
    pwf_fin_clear_closed_by_id = fields.Many2one(
        'res.users', string='CLOSED Clearance By', readonly=True, copy=False)
    pwf_fin_clear_closed_on = fields.Datetime(
        string='CLOSED Clearance On', readonly=True, copy=False)
    pwf_can_edit_finance = fields.Boolean(
        string='Can Edit Finance Clearance',
        compute='_compute_pwf_can_edit_finance')

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.model
    def _pwf_user_is_qa(self, user=None):
        user = user or self.env.user
        if user.has_group('base.group_system') or user.has_group(
                'bt_project_customization.group_qa_group'):
            return True
        return bool(_pwf_job_names(user) & set(TESTER_JOB_NAMES))

    @api.model
    def _pwf_user_is_pm(self, user=None):
        user = user or self.env.user
        if user.has_group('base.group_system'):
            return True
        return bool(_pwf_job_names(user) & set(PM_JOB_NAMES))

    @api.model
    def _pwf_user_is_finance(self, user=None):
        """Only members of the Finance group; administrators do not count."""
        user = user or self.env.user
        return bool(user.has_group(PWF_FINANCE_GROUP))

    @api.depends_context('uid')
    def _compute_pwf_can_edit_reg(self):
        allowed = self._pwf_user_is_qa()
        for project in self:
            project.pwf_can_edit_reg = allowed

    @api.depends_context('uid')
    def _compute_pwf_can_edit_finance(self):
        allowed = self._pwf_user_is_finance()
        for project in self:
            project.pwf_can_edit_finance = allowed

    @api.depends('pwf_approval_ids.state', 'stage_id', 'ft_project_type')
    @api.depends_context('uid')
    def _compute_pwf_approval_state(self):
        Stage = self.env['project.project.stage']
        uat = Stage._ft_lifecycle_stage_map().get('uat')
        is_pm = self._pwf_user_is_pm()
        for project in self:
            pending = project.pwf_approval_ids.filtered(
                lambda a: a.state == 'pending')[:1]
            project.pwf_pending_approval_id = pending
            before_uat = bool(uat) and (
                not project.stage_id
                or Stage._ft_stage_sort_key(project.stage_id)
                < Stage._ft_stage_sort_key(uat))
            project.pwf_can_request_uat_approval = bool(
                is_pm and not pending and before_uat
                and project.ft_project_type == 'implementation')

    @api.depends('pwf_approval_ids.state', 'pwf_approval_ids.request_date',
                 'pwf_approval_ids.target_stage_id',
                 'pwf_approval_ids.decided_by_id',
                 'pwf_approval_ids.rejection_reason')
    def _compute_pwf_uat_request(self):
        for project in self:
            # Latest request = highest id (requests in one transaction share
            # the same request_date).
            latest = project.pwf_approval_ids.filtered(
                lambda a: a.target_stage_id and a.target_stage_id._ft_stage_key() == 'uat'
            ).sorted('id', reverse=True)[:1]
            project.pwf_uat_request_state = latest.state if latest else 'none'
            project.pwf_uat_request_date = latest.request_date if latest else False
            project.pwf_uat_request_decided_by_id = latest.decided_by_id if latest else False
            project.pwf_uat_request_reason = latest.rejection_reason if latest else False

    # ------------------------------------------------------------------
    # Gate evaluation
    # ------------------------------------------------------------------
    def _pwf_x2m_ids(self, fname, vals):
        """Ids the x2many ``fname`` will hold once ``vals`` is written."""
        self.ensure_one()
        ids = list(self[fname].ids)
        if fname not in vals:
            return ids
        commands = vals[fname] or []
        if commands and all(isinstance(c, int) for c in commands):
            return list(commands)
        for command in commands:
            if not isinstance(command, (list, tuple)) or not command:
                continue
            code = command[0]
            if code == Command.CREATE:
                ids.append(0)  # a new record: counts as present
            elif code in (Command.DELETE, Command.UNLINK):
                ids = [i for i in ids if i != command[1]]
            elif code == Command.LINK:
                if command[1] not in ids:
                    ids.append(command[1])
            elif code == Command.CLEAR:
                ids = []
            elif code == Command.SET:
                ids = list(command[2] or [])
        return ids

    def _pwf_value(self, fname, vals):
        """Value of ``fname`` after ``vals`` (values in the same write count)."""
        self.ensure_one()
        field = self._fields[fname]
        if field.type in ('many2many', 'one2many'):
            return self._pwf_x2m_ids(fname, vals)
        if fname not in vals:
            return self[fname]
        value = vals[fname]
        if field.type == 'many2one':
            comodel = self.env[field.comodel_name]
            if isinstance(value, models.BaseModel):
                return value
            return comodel.browse(value).exists() if value else comodel
        return value

    def _pwf_crossed_keys(self, target, stage_map, from_start=False):
        """Gated stage keys between the current stage (excl.) and ``target``
        (incl.), in pipeline order. Empty for backward / same-stage moves.

        ``from_start`` counts from the beginning of the pipeline instead of the
        current stage: a project created, copied or imported straight into a
        stage, or converted to Implementation while sitting in one, must hold
        the evidence of every gated stage up to it."""
        self.ensure_one()
        Stage = self.env['project.project.stage']
        target_key = Stage._ft_stage_sort_key(target)
        current_key = (Stage._ft_stage_sort_key(self.stage_id)
                       if self.stage_id and not from_start else None)
        if current_key is not None and target_key <= current_key:
            return []
        ordered = sorted(stage_map.items(),
                         key=lambda item: Stage._ft_stage_sort_key(item[1]))
        keys = []
        for key, stage in ordered:
            sort_key = Stage._ft_stage_sort_key(stage)
            if key in PWF_GATED_KEYS and sort_key <= target_key and (
                    current_key is None or sort_key > current_key):
                keys.append(key)
        own_key = target._ft_stage_key()
        if own_key in PWF_GATED_KEYS and own_key not in keys:
            keys.append(own_key)
        return keys

    def _pwf_context_approval_ok(self, target):
        """True when this write is the move of a pending approval being
        approved right now by an administrator for this project and stage."""
        self.ensure_one()
        approval_id = self.env.context.get('pwf_approval_id')
        if not approval_id or not self.env.user.has_group('base.group_system'):
            return False
        approval = self.env['ft.pms.stage.approval'].sudo().browse(
            approval_id).exists()
        return bool(
            approval
            and approval.state == 'pending'
            and approval.project_id.id == self.id
            and approval.target_stage_id.id == target.id
            and approval.from_stage_id.id == self.stage_id.id
        )

    def _pwf_gate_missing(self, keys, vals, target, check_approval=True):
        """Numbered-list items of everything missing to cross the stages
        ``keys``. When several stages are crossed (a skip), every item is
        prefixed with the code of the stage that requires it."""
        self.ensure_one()
        missing = []
        multi = len(keys) > 1

        def need(ok, key, label):
            if ok:
                return
            item = '%s \u2013 %s' % (key.upper(), label) if multi else label
            if item not in missing:
                missing.append(item)

        def filled(fname):
            return not is_html_empty(self._pwf_value(fname, vals) or '')

        def finance(key):
            need(self._pwf_value('pwf_fin_clear_%s' % key, vals), key,
                 _("Finance Payment Clearance: Finance must confirm the "
                   "payment clearance for this stage."))

        uat_signoff_listed = False
        for key in keys:
            if key == 'dev':
                need(self._pwf_value('pwf_brd_signoff_attachment_ids', vals), key,
                     _("BRD Sign-off: Upload a screenshot of the client e-mail "
                       "confirming the signed BRD."))
                finance('dev')
            elif key == 'srv':
                need(self._pwf_value('pwf_reg_signed_by_id', vals)
                     and self._pwf_value('pwf_reg_signed_on', vals), key,
                     _("REG Sign-off by QA: QA must sign off the regression "
                       "(REG Signed Off By / On)."))
            elif key == 'uat':
                need(self._pwf_value('pwf_sandbox_review_attachment_ids', vals), key,
                     _("Sandbox Review: Upload the evidence of the client "
                       "sandbox review."))
                finance('uat')
                if check_approval:
                    need(self._pwf_context_approval_ok(target), key,
                         _("Admin Approval: An Administrator must approve the "
                           "move to UAT (use 'Request Admin Approval')."))
            if key in PWF_POST_UAT_KEYS and not uat_signoff_listed:
                # Same evidence for every post-UAT stage: list it once, under
                # the first stage that needs it.
                ok = self._pwf_value('pwf_uat_signoff_attachment_ids', vals)
                need(ok, key,
                     _("Customer UAT Sign-off / Completion E-mail: Upload a "
                       "screenshot of the customer's UAT sign-off or UAT "
                       "completion e-mail."))
                uat_signoff_listed = True
            if key == 'data':
                finance('data')
            if key == 'support':
                finance('support')
            if key == 'closed':
                need(self._pwf_value('pwf_internal_feedback_attachment_ids', vals), key,
                     _("Internal Feedback: Upload a screenshot confirming that "
                       "the internal project feedback has been submitted."))
                need(self._pwf_value('pwf_external_feedback_attachment_ids', vals), key,
                     _("External Review (Partner Portal): Upload a screenshot "
                       "confirming that the external review has been submitted "
                       "through the Partner Portal."))
                finance('closed')
                need(filled('pwf_retro_went_well'), key,
                     _("Retrospective - What Went Well"))
                need(filled('pwf_retro_went_wrong'), key,
                     _("Retrospective - What Went Wrong"))
                need(filled('pwf_retro_to_correct'), key,
                     _("Retrospective - What Needs to Be Corrected"))
        return missing

    @api.model
    def _pwf_gate_message(self, project, stage, missing, placed=False):
        """'Project X cannot be moved to Y. Please complete ...' + numbered list."""
        if stage._ft_stage_key() == 'closed':
            purpose = _("before closing the project")
        elif placed:
            purpose = _("before placing the project in '%s'", stage.name)
        else:
            purpose = _("before moving the project to '%s'", stage.name)
        if placed:
            head = _("Project '%(project)s' cannot be placed in '%(stage)s'.",
                     project=project.display_name, stage=stage.name)
        else:
            head = _("Project '%(project)s' cannot be moved to '%(stage)s'.",
                     project=project.display_name, stage=stage.name)
        return _(
            "%(head)s Please complete the following mandatory actions "
            "%(purpose)s:\n%(items)s",
            head=head,
            purpose=purpose,
            items='\n'.join('%d. %s' % (index, item)
                             for index, item in enumerate(missing, 1)),
        )

    def _pwf_check_stage_gates(self, target, vals, check_approval=True):
        """Raise one UserError listing every missing item, for every project."""
        stage_map = self.env['project.project.stage']._ft_lifecycle_stage_map()
        problems = []
        for project in self:
            new_type = vals.get('ft_project_type', project.ft_project_type)
            # Gate on the current type as well as the new one, so a single
            # write of {type: general, stage: CLOSED} cannot slip past.
            if 'implementation' not in (project.ft_project_type, new_type):
                continue
            if project.stage_id == target:
                continue
            if new_type != 'implementation':
                # Leaving Implementation in this write: lifecycle re-homes the
                # project onto the new type's first stage (ungated), but the
                # shared terminal stage keeps its own gate.
                own_key = target._ft_stage_key()
                keys = [own_key] if own_key in PWF_GATED_KEYS else []
            elif project.ft_project_type != 'implementation':
                # Converted to Implementation in this very write: the current
                # stage belongs to another workflow and says nothing about
                # what this project has already passed, so count from the
                # start of the pipeline.
                keys = project._pwf_crossed_keys(target, stage_map, from_start=True)
            else:
                keys = project._pwf_crossed_keys(target, stage_map)
            if not keys:
                continue
            missing = project._pwf_gate_missing(
                keys, vals, target, check_approval=check_approval)
            if missing:
                problems.append(self._pwf_gate_message(project, target, missing))
        if problems:
            raise UserError('\n\n'.join(problems))

    def _pwf_check_resting_stage_gates(self, vals, check_approval=True):
        """Gate the stage each project already sits on, counted from the start
        of the pipeline (create / copy / import / type conversion)."""
        stage_map = self.env['project.project.stage']._ft_lifecycle_stage_map()
        problems = []
        for project in self:
            stage = project.stage_id
            if not stage or stage._ft_stage_key() not in PWF_GATED_KEYS:
                continue
            keys = project._pwf_crossed_keys(stage, stage_map, from_start=True)
            missing = project._pwf_gate_missing(
                keys, vals, stage, check_approval=check_approval)
            if missing:
                problems.append(self._pwf_gate_message(
                    project, stage, missing, placed=True))
        if problems:
            raise UserError('\n\n'.join(problems))

    @api.model
    def _pwf_stamp_finance(self, vals):
        """Stamp (or clear) the who / when of every clearance flag in vals."""
        for key in PWF_FIN_KEYS:
            flag = 'pwf_fin_clear_%s' % key
            if flag not in vals:
                continue
            if vals[flag]:
                vals['pwf_fin_clear_%s_by_id' % key] = self.env.user.id
                vals['pwf_fin_clear_%s_on' % key] = fields.Datetime.now()
            else:
                vals['pwf_fin_clear_%s_by_id' % key] = False
                vals['pwf_fin_clear_%s_on' % key] = False

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and not self._pwf_user_is_finance():
            if any(vals.get(fname) for vals in vals_list for fname in PWF_FIN_FIELDS):
                raise AccessError(_(
                    "Only Finance can set a Finance payment clearance."))
        for vals in vals_list:
            self._pwf_stamp_finance(vals)
        projects = super().create(vals_list)
        if not self.env.su:
            # Checked on the created records, after ft_project_lifecycle has
            # homed each one onto a stage valid for its type. No approval can
            # exist for a record that did not exist yet, so creating straight
            # into UAT or beyond is refused.
            projects.filtered(
                lambda p: p.ft_project_type == 'implementation'
            )._pwf_check_resting_stage_gates({})
        return projects

    def _pwf_fin_changed(self, vals):
        """True when vals changes a Finance clearance field on any project."""
        for fname in PWF_FIN_FIELDS:
            if fname not in vals:
                continue
            field = self._fields[fname]
            new = vals[fname]
            for project in self:
                old = project[fname]
                if field.type == 'many2one':
                    old = old.id
                    if isinstance(new, models.BaseModel):
                        new = new.id
                if (old or False) != (new or False):
                    return True
        return False

    def _pwf_check_write_rights(self, vals):
        # The lock / unlock check lives in project_project_lock.py.
        if (any(fname in vals for fname in PWF_FIN_FIELDS)
                and not self._pwf_user_is_finance()
                and self._pwf_fin_changed(vals)):
            raise AccessError(_(
                "Only Finance can change a Finance payment clearance."))
        if any(fname in vals for fname in PWF_REG_FIELDS) and not self._pwf_user_is_qa():
            raise AccessError(_(
                "Only QA (Software Tester, Junior Software Tester, Testing Lead) "
                "or an Administrator can edit the REG sign-off."))

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------
    def write(self, vals):
        vals = dict(vals)
        Stage = self.env['project.project.stage']
        target = Stage
        if vals.get('stage_id'):
            target = Stage.browse(vals['stage_id']).exists()

        # A clearance flag re-stating its current value changes nothing: drop
        # it, so it neither needs Finance rights nor re-stamps who / when.
        for key in PWF_FIN_KEYS:
            flag = 'pwf_fin_clear_%s' % key
            if flag in vals and self and all(
                    bool(project[flag]) == bool(vals[flag]) for project in self):
                del vals[flag]
        if not self.env.su:
            self._pwf_check_write_rights(vals)
        self._pwf_stamp_finance(vals)

        if target and not self.env.su:
            self._pwf_check_stage_gates(target, vals)
        if (not self.env.su and not target
                and vals.get('ft_project_type') == 'implementation'):
            # Converted to Implementation while sitting on a gated stage the
            # type shares (CLOSED): it must already carry that evidence.
            self._pwf_check_resting_stage_gates(vals, check_approval=False)

        # QA may sign REG off, and Finance may clear a payment, without
        # holding write access on the project: elevate a write that touches
        # nothing but the REG sign-off / the Finance clearances (the rights on
        # those fields were checked above).
        records = self
        if (not self.env.su and vals
                and (set(vals) <= set(PWF_REG_FIELDS)
                     or set(vals) <= set(PWF_FIN_FIELDS))
                and not self.has_access('write')):
            self.check_access('read')
            records = self.sudo()

        track = (
            not self.env.su
            and not self.env.context.get('pwf_in_stage_write')
            and ('stage_id' in vals or 'ft_project_type' in vals)
        )
        old_stages = {project.id: project.stage_id for project in self} if track else {}
        if track:
            records = records.with_context(pwf_in_stage_write=True)
        result = super(ProjectProject, records).write(vals)
        if track:
            changed = self.filtered(
                lambda p: p.stage_id != old_stages.get(p.id))
            if changed:
                changed._pwf_send_stage_notification(old_stages)
        return result

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------
    def _pwf_stage_notify_recipients(self):
        """(partners, extra e-mails) for a stage-change notification: the
        customer, the Project Manager, the Settings contacts and info e-mails,
        deduped on e-mail address (case-insensitive)."""
        self.ensure_one()
        company = (self.company_id or self.env.company).sudo()
        candidates = (
            self.partner_id
            | self.sudo().user_id.partner_id
            | company.pwf_stage_notify_partner_ids
        ).sudo()
        partners = self.env['res.partner']
        seen = set()
        for partner in candidates:
            key = email_normalize(partner.email or '') or (partner.email or '').strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            partners |= partner
        emails = []
        for raw in company._pwf_stage_notify_emails():
            normalized = email_normalize(raw) or raw
            if normalized not in seen:
                seen.add(normalized)
                emails.append(normalized)
        return partners, emails

    @api.model
    def _pwf_stage_desc(self, stage):
        """Human description of a stage ("Data Upload"); its name if unknown."""
        if not stage:
            return ''
        return PWF_STAGE_DESCRIPTIONS.get(stage._ft_stage_key()) or stage.name or ''

    @api.model
    def _pwf_stage_label(self, stage):
        """Stage label "DATA - Data Upload" (en dash); the bare name when it
        already carries the description (or none is known); '-' if no stage."""
        if not stage:
            return '-'
        name = stage.name or ''
        desc = PWF_STAGE_DESCRIPTIONS.get(stage._ft_stage_key())
        if not desc or desc.lower() in name.lower():
            return name or '-'
        return '%s \u2013 %s' % (name, desc)

    def _pwf_send_stage_notification(self, old_stages):
        template = self.env.ref(
            'ft_pms_planning_workflow.mail_template_pwf_stage_change',
            raise_if_not_found=False)
        if not template:
            return
        mover = self.env.user
        now = fields.Datetime.now()
        moved_on_str = format_datetime(
            self.env, now, tz=mover.tz or 'UTC',
            dt_format=PWF_MOVED_ON_FORMAT, lang_code='en_US')
        # The next stage is computed from the new stage: drop the cached value.
        self.invalidate_recordset(['pwf_next_stage_id'])
        for project in self:
            partners, emails = project._pwf_stage_notify_recipients()
            if not partners and not emails:
                continue
            old_stage = old_stages.get(project.id)
            new_stage = project.stage_id
            pm = project.sudo().user_id
            company = project.company_id or self.env.company
            # Queued (no force_send): a rollback of the transaction discards it.
            template.sudo().with_context(
                pwf_old_stage_name=old_stage.name if old_stage else '',
                pwf_new_stage_name=new_stage.name or '',
                pwf_moved_by=mover.name or '',
                pwf_moved_on=now,
                pwf_greeting_name=project.sudo().partner_id.name or '',
                pwf_new_stage_code=new_stage.name or '',
                pwf_new_stage_desc=self._pwf_stage_desc(new_stage),
                pwf_old_stage_label=self._pwf_stage_label(old_stage),
                pwf_new_stage_label=self._pwf_stage_label(new_stage),
                pwf_next_stage_label=self._pwf_stage_label(project.pwf_next_stage_id),
                pwf_moved_on_str=moved_on_str,
                pwf_pm_name=pm.name or '',
                pwf_pm_email=pm.email or '',
                pwf_company_name=company.sudo().name or '',
            ).send_mail(
                project.id,
                force_send=False,
                # Sender forced here too, so a template edited in the UI can't
                # make the mover (author) appear as sender.
                email_values={
                    'recipient_ids': [Command.set(partners.ids)],
                    'email_to': ','.join(emails) or False,
                    'email_from': PWF_STAGE_EMAIL_FROM,
                    'reply_to': PWF_STAGE_REPLY_TO,
                },
            )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_pwf_reg_signoff(self):
        """QA stamps the REG sign-off as theirs, now."""
        if not self._pwf_user_is_qa():
            raise AccessError(_(
                "Only QA or an Administrator can sign off the regression."))
        # Current Status / Open Issues are optional: the sign-off itself is
        # what the SRV gate requires.
        self.write({
            'pwf_reg_signed_by_id': self.env.user.id,
            'pwf_reg_signed_on': fields.Datetime.now(),
        })
        return True

    def _pwf_finance_set(self, value):
        """Grant / revoke the Finance clearance of the stage named by the
        ``pwf_fin_key`` context key. Finance users usually have no write
        access on the project (the form is read-only for them), so the flag
        is written through sudo once the Finance group and read access on
        the project have been checked."""
        key = self.env.context.get('pwf_fin_key')
        if key not in PWF_FIN_KEYS:
            raise UserError(_("Unknown Finance clearance stage: %s", key))
        if not self.env.su and not self._pwf_user_is_finance():
            raise AccessError(_(
                "Only Finance can grant or revoke a Finance payment clearance."))
        self.check_access('read')
        user = self.env.user  # the real user, even under sudo()
        flag = 'pwf_fin_clear_%s' % key
        now = fields.Datetime.now()
        for project in self:
            if bool(project[flag]) == bool(value):
                continue
            project.sudo().write({
                flag: bool(value),
                'pwf_fin_clear_%s_by_id' % key: user.id if value else False,
                'pwf_fin_clear_%s_on' % key: now if value else False,
            })
            if value:
                body = _("Finance payment clearance granted for %(stage)s by %(user)s",
                         stage=key.upper(), user=user.name)
            else:
                body = _("Finance payment clearance revoked for %(stage)s by %(user)s",
                         stage=key.upper(), user=user.name)
            project.sudo().message_post(
                body=body, author_id=user.partner_id.id,
                message_type='comment', subtype_xmlid='mail.mt_note')
        return True

    def action_pwf_finance_grant(self):
        return self._pwf_finance_set(True)

    def action_pwf_finance_revoke(self):
        return self._pwf_finance_set(False)

    def action_request_uat_approval(self):
        """PM / admin asks an Administrator to approve the move into UAT."""
        self.ensure_one()
        if not self._pwf_user_is_pm():
            raise AccessError(_(
                "Only a Project Manager or an Administrator can request a UAT approval."))
        if self.ft_project_type != 'implementation':
            raise UserError(_("UAT approval applies to Implementation projects only."))
        Stage = self.env['project.project.stage']
        uat = Stage._ft_lifecycle_stage_map().get('uat')
        if not uat:
            raise UserError(_("No UAT stage is configured."))
        if self.stage_id and Stage._ft_stage_sort_key(self.stage_id) >= Stage._ft_stage_sort_key(uat):
            raise UserError(_("Project '%s' has already reached UAT.", self.display_name))
        Approval = self.env['ft.pms.stage.approval'].sudo()
        if Approval.search_count([
            ('project_id', '=', self.id),
            ('target_stage_id', '=', uat.id),
            ('state', '=', 'pending'),
        ]):
            raise UserError(_(
                "A UAT approval request is already pending for project '%s'.",
                self.display_name))
        # Everything but the approval itself must already be in place.
        self._pwf_check_stage_gates(uat, {}, check_approval=False)
        self._ft_check_stage_entry_dates(uat, {})
        approval = Approval.create({
            'project_id': self.id,
            'from_stage_id': self.stage_id.id,
            'target_stage_id': uat.id,
            'requested_by_id': self.env.user.id,
        })
        self.message_post(body=_(
            "Admin approval requested to move the project to %s.", uat.name))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'ft.pms.stage.approval',
            'res_id': approval.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_pwf_approve_pending(self):
        self.ensure_one()
        if not self.pwf_pending_approval_id:
            raise UserError(_("There is no pending approval request."))
        return self.pwf_pending_approval_id.action_approve()

    def action_pwf_reject_pending(self):
        self.ensure_one()
        if not self.pwf_pending_approval_id:
            raise UserError(_("There is no pending approval request."))
        return self.pwf_pending_approval_id.action_reject()
