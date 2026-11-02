# -*- coding: utf-8 -*-
"""Monthly AMC milestone creation (requirements 36, 37, 50).

``_amc_ensure_monthly_milestone(period_start)`` is the single entry point:
the daily cron (current month), the install hook (previous + current month),
the "Create This Month's Milestone" button and the task deployment link
(month the task was deployed in) all go through it. It is idempotent - the
UNIQUE(project_id, amc_period_start) constraint backs it up against two
workers racing - and it creates the milestone whether or not any task was
worked on, approved or deployed in that month: the milestone is the billing
line of the month, the tasks are what gets attached to it later.
"""
import logging

from psycopg2 import IntegrityError

from odoo import _, api, models
from odoo.exceptions import UserError

from odoo.addons.ft_amc_monthly_timesheet.models.periods import month_end, month_start

_logger = logging.getLogger(__name__)


class ProjectProject(models.Model):
    _inherit = 'project.project'

    # ------------------------------------------------------------------
    # eligibility
    # ------------------------------------------------------------------
    def _amc_milestone_eligible(self, period_start):
        """Active AMC project, not a template, not CLOSED, not on hold, whose
        contract dates cover the month. ``amc_report_enabled`` is deliberately
        NOT consulted: the milestone exists for billing even when the
        timesheet e-mail is switched off (the switch is copied onto the
        milestone as its own default instead)."""
        self.ensure_one()
        project = self.sudo()  # stage_id is group-restricted on the core model
        if not project.active or project.ft_project_type != 'amc':
            return False
        if 'is_template' in project._fields and project.is_template:
            return False
        stage = project.stage_id
        if stage and stage._ft_stage_key() == 'closed':
            return False
        if 'pl_on_hold' in project._fields and project.pl_on_hold:
            return False
        return project._amc_contract_covers(period_start)

    @api.model
    def _amc_milestone_candidates(self):
        """Projects the cron / hook look at; the per-month checks (stage,
        hold, contract dates) are done by _amc_milestone_eligible."""
        domain = [('active', '=', True), ('ft_project_type', '=', 'amc')]
        if 'is_template' in self._fields:
            domain.append(('is_template', '=', False))
        return self.sudo().search(domain, order='id')

    # ------------------------------------------------------------------
    # ensure
    # ------------------------------------------------------------------
    def _amc_find_monthly_milestone(self, period_start):
        self.ensure_one()
        return self.env['project.custom.milestone'].sudo().search([
            ('project_id', '=', self.id),
            ('is_amc_monthly', '=', True),
            ('amc_period_start', '=', month_start(period_start)),
        ], limit=1)

    def _amc_monthly_milestone_vals(self, period_start):
        self.ensure_one()
        Milestone = self.env['project.custom.milestone']
        period_end = month_end(period_start)
        return {
            'project_id': self.id,
            'name': Milestone._amc_milestone_name(period_start),
            'milestone_id': Milestone._amc_milestone_code(period_start),
            'description': _("Monthly AMC support milestone for %s.",
                             Milestone._amc_period_label(period_start)),
            'is_amc_monthly': True,
            'amc_period_start': period_start,
            'amc_period_end': period_end,
            # The billing period closes with the month. Never changed afterwards:
            # project_date_extension guards due_date writes, and the kick-off
            # sync ignores AMC monthly milestones (see project_custom_milestone).
            'due_date': period_end,
            'status': 'not_started',
            # Requirement 44: the project-level switch becomes the milestone's
            # own default; it can be flipped per month afterwards.
            'amc_send_email': bool(self.sudo().amc_report_enabled),
        }

    def _amc_ensure_monthly_milestone(self, period_start):
        """The AMC monthly milestone of this project for the month of
        ``period_start``: existing one, or a new one when the project is
        eligible for that month, else an empty recordset. Always sudo: the
        callers are crons, hooks and task actions run by users who may not
        write milestones themselves."""
        self.ensure_one()
        period_start = month_start(period_start)
        existing = self._amc_find_monthly_milestone(period_start)
        if existing:
            return existing
        Milestone = self.env['project.custom.milestone'].sudo()
        if not self._amc_milestone_eligible(period_start):
            _logger.info("AMC project %s (%s): not eligible for a %s milestone, none created.",
                         self.id, self.sudo().name, period_start.strftime('%Y-%m'))
            return Milestone
        vals = self._amc_monthly_milestone_vals(period_start)
        try:
            with self.env.cr.savepoint():
                milestone = Milestone.create(vals)
        except IntegrityError:
            # Created concurrently (cron worker and a deployment at the same time).
            return self._amc_find_monthly_milestone(period_start)
        milestone.message_post(body=_(
            "AMC monthly milestone created automatically for %s.",
            Milestone._amc_period_label(period_start)))
        return milestone

    # ------------------------------------------------------------------
    # cron / button
    # ------------------------------------------------------------------
    @api.model
    def _cron_ft_amc_create_monthly_milestones(self):
        """Daily: make sure the CURRENT month's milestone exists for every
        eligible AMC project. Running on the 1st creates it; every later run
        finds it already there (or creates it for a project that became
        eligible mid-month, e.g. a contract that started today)."""
        Report = self.env['ft.amc.monthly.report'].sudo()
        created = 0
        for project in self._amc_milestone_candidates():
            today = Report._local_today(project.company_id or self.env.company)
            before = project._amc_find_monthly_milestone(month_start(today))
            if project._amc_ensure_monthly_milestone(month_start(today)) and not before:
                created += 1
        _logger.info("AMC monthly milestones: %s created by the daily cron.", created)
        return created

    def action_ft_amc_create_current_milestone(self):
        """Project form (AMC tab): create / open this month's milestone."""
        self.ensure_one()
        self.env['ft.amc.monthly.report']._check_manager()
        if self.ft_project_type != 'amc':
            raise UserError(_("Monthly payment milestones are only created for AMC projects."))
        Report = self.env['ft.amc.monthly.report']
        today = Report._local_today(self.company_id or self.env.company)
        milestone = self._amc_ensure_monthly_milestone(month_start(today))
        if not milestone:
            raise UserError(_(
                "Project '%s' is not eligible for a milestone this month: it must be "
                "an active AMC project that is not closed or on hold, with contract "
                "dates (Start Date / End Date) covering the month.", self.display_name))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'project.custom.milestone',
            'res_id': milestone.id,
            'view_mode': 'form',
            'target': 'current',
        }
