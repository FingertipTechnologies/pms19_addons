# -*- coding: utf-8 -*-
"""Project side of the payment milestone plan.

* The plan total (sum of ``custom_milestone_ids.percentage``) and whether it
  is 100% (requirement 52), shown in the Milestones tab.
* Requirement 54: the 100% plan is required to leave KICKOFF, and for every
  later forward move. Implemented on top of ft_pms_planning_workflow's gate
  framework: ``_pwf_transition_missing`` gains one more item, so the stage
  write refuses the move with the usual "cannot be moved ... Please complete"
  message and the form's Missing-for-Next-Stage checklist shows it live.
  Project CREATION is not gated on 100% (it already needs one milestone and
  the plan is entered during KICKOFF).
* Requirement 56: ``ft_milestone_plan_locked`` (the project has left
  KICKOFF) and ``ft_milestone_plan_editable``.
* Requirements 51 / 53 (19.0.1.2.0): a new Implementation project created
  without milestones of its own receives every active Milestone Template as
  a 0% milestone (no due date, no amount), so the Milestones tab lists the
  agreed names from the start and the PM only fills in the percentages during
  KICKOFF. The same happens when a project is converted to Implementation
  with no payment milestone yet.
"""
from odoo import _, api, fields, models
from odoo.fields import Command

from .milestone_template import PERCENT_DIGITS, ft_format_percent, ft_percent_is_100
from .project_custom_milestone import LOCK_SNAPSHOT_CONTEXT_KEY

# The plan may be built freely only while the project is in KICKOFF: this is
# the stage during which the customer agreement is drafted. Everything after
# it (DISC included) is locked - the plan is required to ENTER DISC.
UNLOCKED_STAGE_KEYS = ('kickoff',)


class ProjectProject(models.Model):
    _inherit = 'project.project'

    ft_milestone_percentage_total = fields.Float(
        string='Milestone Plan Total %', compute='_compute_ft_milestone_plan',
        digits=(16, PERCENT_DIGITS),
        help='Sum of the percentages of the project milestones.')
    ft_milestone_plan_ok = fields.Boolean(
        string='Milestone Plan Complete', compute='_compute_ft_milestone_plan',
        help='True when the milestone percentages add up to 100%.')
    ft_milestone_plan_locked = fields.Boolean(
        string='Milestone Plan Locked', compute='_compute_ft_milestone_plan_state',
        help='True for an Implementation project that has left KICKOFF: the '
             'agreed milestones change only through a Milestone Change Request.')
    ft_milestone_plan_editable = fields.Boolean(
        string='Milestone Plan Editable', compute='_compute_ft_milestone_plan_state',
        help='Technical: Implementation project in KICKOFF / DISC whose plan '
             'is not locked for this user.')
    ft_milestone_completion_email = fields.Boolean(
        string='E-mail Customer on Milestone Completion', default=True,
        help='Implementation projects: when a payment milestone is marked '
             'Completed, e-mail the customer (template "Implementation: '
             'Milestone Completed"). AMC monthly milestones have their own '
             'monthly timesheet e-mail and are not concerned.')
    ft_milestone_change_request_ids = fields.One2many(
        'ft.milestone.change.request', 'project_id',
        string='Milestone Change Requests')
    ft_milestone_change_request_count = fields.Integer(
        compute='_compute_ft_milestone_change_request_count')

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends('custom_milestone_ids.percentage')
    def _compute_ft_milestone_plan(self):
        for project in self:
            total = project._ft_milestone_total({})
            project.ft_milestone_percentage_total = total
            project.ft_milestone_plan_ok = ft_percent_is_100(total)

    @api.depends('stage_id', 'ft_project_type')
    @api.depends_context('uid')
    def _compute_ft_milestone_plan_state(self):
        bypass = self.env['project.custom.milestone']._ft_milestone_user_may_bypass()
        for project in self:
            locked = project._ft_milestone_plan_is_locked()
            project.ft_milestone_plan_locked = locked
            # Templates are for the early stages (requirement 51). In DISC the
            # plan is already locked, so only an approver still gets the button
            # there; the server refuses everybody else anyway.
            project.ft_milestone_plan_editable = bool(
                project._pl_in_early_stage() and (not locked or bypass))

    @api.depends('ft_milestone_change_request_ids')
    def _compute_ft_milestone_change_request_count(self):
        for project in self:
            project.ft_milestone_change_request_count = len(
                project.ft_milestone_change_request_ids)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _ft_milestone_plan_is_locked(self):
        """Requirement 56: an Implementation project that has left KICKOFF.
        Projects without a stage and non-Implementation projects are never
        locked."""
        self.ensure_one()
        return bool(
            self.ft_project_type == 'implementation'
            and self.stage_id
            and self.stage_id._ft_stage_key() not in UNLOCKED_STAGE_KEYS
        )

    def _ft_milestone_contract_value(self):
        """Contract value the milestone percentages apply to, or 0.0.

        No PMS module defines a contract / budget amount on the project; the
        only money the project carries is the linked Sales Order
        (sale_project.sale_order_id, via sale_timesheet), so its untaxed total
        is used when present. Read under sudo: a Project Manager need not have
        Sales access to apply a template. Repoint this one method should a
        dedicated contract value field be added later."""
        self.ensure_one()
        if 'sale_order_id' not in self._fields:
            return 0.0
        order = self.sudo().sale_order_id
        return order.amount_untaxed if order else 0.0

    def _ft_milestone_total(self, vals):
        """Sum of the milestone percentages once ``vals`` is written.

        The x2many commands of the same write count (a plan entered or fixed
        in the same save as the stage move): the percentage of a new line is
        read from its (0, 0, values) command, an updated one from its
        (1, id, values) command. On the unsaved form record the lines only
        have a NewId and are read from the cache like any other."""
        self.ensure_one()
        current = {m.id: m.percentage for m in self.custom_milestone_ids}
        if 'custom_milestone_ids' not in vals:
            return sum(current.values())
        Milestone = self.env['project.custom.milestone']
        commands = vals['custom_milestone_ids'] or []
        if commands and all(isinstance(c, int) for c in commands):
            return sum(Milestone.browse(commands).mapped('percentage'))
        added = []
        for command in commands:
            if not isinstance(command, (list, tuple)) or not command:
                continue
            code = command[0]
            if code == Command.CREATE:
                added.append((command[2] or {}).get('percentage') or 0.0)
            elif code == Command.UPDATE:
                values = command[2] or {}
                if 'percentage' in values:
                    current[command[1]] = values['percentage'] or 0.0
                elif command[1] not in current:
                    current[command[1]] = Milestone.browse(command[1]).percentage
            elif code in (Command.DELETE, Command.UNLINK):
                current.pop(command[1], None)
            elif code == Command.LINK:
                if command[1] not in current:
                    current[command[1]] = Milestone.browse(command[1]).percentage
            elif code == Command.CLEAR:
                current = {}
            elif code == Command.SET:
                current = {
                    m.id: m.percentage
                    for m in Milestone.browse(command[2] or [])}
        return sum(current.values()) + sum(added)

    @api.model
    def _ft_template_milestone_commands(self, existing_names=()):
        """One2many create commands for every active Milestone Template whose
        name is not in ``existing_names`` (compared trimmed, case-insensitive),
        in template order. Read under sudo: creating a project must not
        depend on the user's right to read the templates."""
        taken = {(name or '').strip().lower() for name in existing_names}
        templates = self.env['ft.milestone.template'].sudo().search([])
        return [
            Command.create(template._ft_milestone_vals())
            for template in templates
            if (template.name or '').strip().lower() not in taken
        ]

    def _ft_has_custom_milestones(self, vals):
        """True when the project will hold at least one payment milestone
        once ``vals`` is written (lines added in the same save count)."""
        self.ensure_one()
        return bool(self._pwf_value('custom_milestone_ids', vals))

    @api.model
    def _pwf_milestone_item(self):
        """Implementation projects get the template milestones on creation,
        so the gate asks to update the plan rather than to add a milestone."""
        return _(
            "Milestones: Update the milestone plan in the Milestones tab: the "
            "project's milestones with their percentages, totalling "
            "100%, and their due dates.")

    @api.model
    def _ft_milestone_plan_item(self, total):
        """The gate checklist line for an incomplete plan."""
        return _(
            "Payment Milestones: the milestone percentages must add up to "
            "100%% (currently %(total)s%%). Adjust them in the Milestones tab.",
            total=ft_format_percent(total))

    # ------------------------------------------------------------------
    # Stage gate (ft_pms_planning_workflow)
    # ------------------------------------------------------------------
    def _pwf_transition_missing(self, keys, vals, target, check_approval=True,
                                require_milestone=True):
        """Requirement 54: on top of the base rule (at least one milestone
        for every forward move of an Implementation project) the plan must
        total 100%. ``require_milestone`` is what the base passes only for
        Implementation projects, so the same flag scopes this rule; the
        superuser skip happens in the caller, like every other gate."""
        missing = super()._pwf_transition_missing(
            keys, vals, target, check_approval=check_approval,
            require_milestone=require_milestone)
        # Only the payment plan (custom_milestone_ids) is judged, and only
        # when one exists: a project that satisfies the base rule through
        # core project.milestone records alone (the PMS form never shows
        # those, but the base rule and older fixtures accept them) has no
        # plan to total, and a project with no milestone at all is already
        # refused by the base item - a second "0%" line would only repeat it.
        if (require_milestone and self._pwf_is_forward_move(target)
                and self._ft_has_custom_milestones(vals)):
            total = self._ft_milestone_total(vals)
            if not ft_percent_is_100(total):
                item = self._ft_milestone_plan_item(total)
                if item not in missing:
                    missing.append(item)
        return missing

    @api.depends('custom_milestone_ids.percentage')
    def _compute_pwf_next_stage_missing(self):
        """Same compute; the extra dependency makes the Missing-for-Next-Stage
        checklist follow the percentages as they are typed in the form."""
        super()._compute_pwf_next_stage_missing()

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        # A new Implementation project with no milestone of its own starts
        # with the Milestone Templates at 0%. The commands are added to the
        # create values, so ft_pms_planning_workflow's "at least one
        # milestone" creation rule is met by the same create, and the lines
        # are created once the project sits on KICKOFF (ft_project_lifecycle
        # homes it there before the One2many commands run), i.e. unlocked.
        # A project explicitly created with its own plan is left as entered.
        if not self.env.context.get('ft_skip_template_milestones'):
            for vals in vals_list:
                if (vals.get('ft_project_type') == 'implementation'
                        and not vals.get('custom_milestone_ids')
                        and not vals.get('is_template')):
                    commands = self._ft_template_milestone_commands()
                    if commands:
                        vals['custom_milestone_ids'] = commands
        return super().create(vals_list)

    def write(self, vals):
        if (vals.get('ft_project_type') == 'implementation'
                and 'custom_milestone_ids' not in vals
                and not self.env.context.get('ft_skip_template_milestones')):
            # Converted to Implementation without a payment milestone yet:
            # same start as a new project. The plan did not exist before this
            # write, so it is not locked for it (the current stage belongs to
            # the previous workflow and must not be read as "after KICKOFF").
            needing = self.filtered(
                lambda p: p.ft_project_type != 'implementation'
                and not p.custom_milestone_ids)
            commands = needing and self._ft_template_milestone_commands()
            if needing and commands:
                rest = self - needing
                res = needing.with_context(**{
                    LOCK_SNAPSHOT_CONTEXT_KEY: {p.id: False for p in needing},
                })._ft_write_plan_aware(dict(vals, custom_milestone_ids=commands))
                if rest:
                    res = rest._ft_write_plan_aware(vals)
                return res
        res = self._ft_write_plan_aware(vals)
        if not self.env.context.get('ft_skip_template_milestones'):
            # Every save of an Implementation project completes its plan with
            # the Milestone Templates it does not have yet (0%, no due date),
            # existing milestones untouched.
            self._ft_add_missing_template_milestones()
        return res

    def _ft_add_missing_template_milestones(self):
        """Add, at 0%, the active Milestone Templates whose name is missing on
        each Implementation project of ``self`` (existing milestones are kept
        as they are). Returns the number of milestones added. Done under sudo
        and outside the plan lock: a template line at 0% changes no agreed
        figure, it only completes the plan the PM maintains."""
        added = 0
        for project in self.filtered(
                lambda p: p.ft_project_type == 'implementation'
                and not p.is_template):
            commands = self._ft_template_milestone_commands(
                project.custom_milestone_ids.mapped('name'))
            if not commands:
                continue
            project.sudo().with_context(**{
                LOCK_SNAPSHOT_CONTEXT_KEY: {project.id: False},
                'ft_skip_template_milestones': True,
            }).write({'custom_milestone_ids': commands})
            added += len(commands)
        return added

    def _ft_write_plan_aware(self, vals):
        if (LOCK_SNAPSHOT_CONTEXT_KEY not in self.env.context
                and 'custom_milestone_ids' in vals and 'stage_id' in vals
                and not self.env.su):
            # The milestone lines of this write are judged against the stage
            # the project is LEAVING: by the time the One2many commands run,
            # the new stage already sits in the cache and a PM completing the
            # plan while moving KICKOFF -> DISC would be refused by the lock.
            snapshot = {
                project.id: project._ft_milestone_plan_is_locked()
                for project in self}
            return super(ProjectProject, self.with_context(
                **{LOCK_SNAPSHOT_CONTEXT_KEY: snapshot})).write(vals)
        return super(ProjectProject, self).write(vals)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_ft_view_milestone_change_requests(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'ft_implementation_milestone.action_ft_milestone_change_request')
        action.update({
            'domain': [('project_id', '=', self.id)],
            'context': {
                **self.env.context,
                'default_project_id': self.id,
            },
        })
        return action
