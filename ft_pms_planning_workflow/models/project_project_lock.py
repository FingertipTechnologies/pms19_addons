# -*- coding: utf-8 -*-
"""Project lock (PS-10).

A project is locked automatically while it is CLOSED or on HOLD (stage or the
``pl_on_hold`` flag) or overdue, and unlocked automatically once none of those
holds any more. A locked project accepts no new tasks and no timesheet entries
(enforced in project_task_workflow.py / account_analytic_line.py).

Administrator overrides:
  * unlocking by hand sets ``pwf_manual_unlock``: the project stays unlocked
    until its stage changes (the override is then cleared and the rules apply
    again);
  * locking by hand sets ``pwf_manual_lock``: the project stays locked until an
    administrator unlocks it.

The lock is re-evaluated after every create / write touching the stage, the
hold flag, the project type or any date field, and by the daily cron (the
overdue state depends on today's date).

Overdue stage freeze: while an Implementation project is overdue (a milestone
date has passed and the project has not reached that milestone's stage), its
stage cannot be changed at all - forward or backward, by anyone, administrators
included - until a Date Extension Request moves the missed date forward. The
approval flow (project_date_extension) writes the extended date under sudo,
which clears ``ft_is_overdue`` and with it the freeze. Only superuser / sudo
writes (crons, migrations, server actions) are exempt. The administrator's
manual unlock frees tasks and timesheets only; it never frees the stage.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

# Fields only an administrator may change by hand.
PWF_ADMIN_FIELDS = ('pwf_locked', 'pwf_manual_unlock', 'pwf_manual_lock')
# Stage keys (project.project.stage._ft_stage_key) that lock the project.
PWF_LOCK_STAGE_KEYS = ('closed', 'hold')
PWF_LOCK_TRIGGER_FIELDS = ('stage_id', 'pl_on_hold', 'ft_project_type', 'date')


class ProjectProjectLock(models.Model):
    _inherit = 'project.project'

    pwf_locked = fields.Boolean(
        string='Locked', copy=False, tracking=True,
        help='A locked project accepts no new tasks and no timesheet entries. '
             'Set automatically while the project is closed, on hold or '
             'overdue and released automatically once it no longer is; an '
             'Administrator can override it.',
    )
    pwf_manual_unlock = fields.Boolean(
        string='Unlocked by Administrator', copy=False,
        help='Set when an Administrator unlocks the project: it then stays '
             'unlocked until its stage changes. The unlock frees tasks and '
             'timesheets only: an overdue project still cannot change stage '
             'until its missed date is extended (Date Extension Request).',
    )
    pwf_manual_lock = fields.Boolean(
        string='Locked by Administrator', copy=False,
        help='Set when an Administrator locks the project by hand: it then '
             'stays locked until an Administrator unlocks it.',
    )

    # ------------------------------------------------------------------
    # Rules
    # ------------------------------------------------------------------
    def _pwf_should_lock(self):
        """True when the lock rules (closed / hold / overdue) apply."""
        self.ensure_one()
        stage_key = self.stage_id._ft_stage_key() if self.stage_id else False
        return bool(stage_key in PWF_LOCK_STAGE_KEYS
                    or self.pl_on_hold
                    or self.ft_is_overdue)

    def _pwf_target_lock(self):
        self.ensure_one()
        if self.pwf_manual_lock:
            return True
        if self.pwf_manual_unlock:
            return False
        return self._pwf_should_lock()

    def _pwf_evaluate_lock(self):
        """Bring pwf_locked in line with the rules and the admin overrides."""
        projects = self.sudo().with_context(pwf_lock_eval=True).exists()
        to_lock = projects.browse()
        to_unlock = projects.browse()
        for project in projects:
            locked = project._pwf_target_lock()
            if locked and not project.pwf_locked:
                to_lock |= project
            elif not locked and project.pwf_locked:
                to_unlock |= project
        if to_lock:
            to_lock.write({'pwf_locked': True})
        if to_unlock:
            to_unlock.write({'pwf_locked': False})
        return to_lock, to_unlock

    @api.model
    def _pwf_lock_triggered(self, vals):
        return any(
            fname in PWF_LOCK_TRIGGER_FIELDS or fname.endswith('_date')
            for fname in vals
        )

    def _pwf_check_lock_rights(self, vals):
        if self.env.su or self.env.user.has_group('base.group_system'):
            return
        if any(
            bool(project[fname]) != bool(vals[fname])
            for project in self for fname in PWF_ADMIN_FIELDS if fname in vals
        ):
            raise AccessError(_("Only an Administrator can lock or unlock a project."))

    def _pwf_check_overdue_stage_change(self, vals):
        """Refuse a stage change of an overdue Implementation project.

        "If UAT date is 20-10-2026 no one can move any stage on the 21st
        without a date extension": the overdue state is read from the record
        as it stands BEFORE the write, so a date slipped into the same write
        as the stage never lifts the freeze - the extension is applied by the
        approval flow in a write of its own (sudo, exempt here), after which
        the next stage move passes. Every direction and every user is held to
        it, administrators and the manual unlock included; only superuser /
        sudo writes (crons, migrations, the approval flow) go through.

        Implementation projects only: the milestone dates belong to that
        lifecycle, and an AMC / General project (whose stages carry no dated
        milestone) must never be frozen by a stray date on it.
        """
        if self.env.su or 'stage_id' not in vals:
            return
        target_id = vals['stage_id'] or False
        target = self.env['project.project.stage'].browse(target_id).exists()
        for project in self:
            if project.stage_id.id == target_id:
                # An unrelated write re-stating the stage is not a move.
                continue
            if project.ft_project_type != 'implementation' or not project.ft_is_overdue:
                continue
            raise UserError(_(
                "Project '%(project)s' cannot be moved to '%(stage)s' while it "
                "is overdue: %(reason)s. Submit a Date Extension Request and "
                "have it approved first; stage changes stay blocked until the "
                "overdue date is extended.",
                project=project.display_name,
                stage=target.name or '-',
                reason=project.ft_overdue_reason,
            ))

    # ------------------------------------------------------------------
    # Form hint
    # ------------------------------------------------------------------
    @api.depends('ft_is_overdue', 'ft_overdue_reason')
    def _compute_pwf_next_stage_missing(self):
        """Prepend the overdue freeze to the "Missing for Next Stage" list, so
        the form says why a move will be refused before the user tries it."""
        super()._compute_pwf_next_stage_missing()
        for project in self:
            if project.ft_project_type != 'implementation' or not project.ft_is_overdue:
                continue
            line = _("Overdue: %s. Extend the date first.", project.ft_overdue_reason)
            project.pwf_next_stage_missing = '\n'.join(
                part for part in (line, project.pwf_next_stage_missing) if part)

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and not self.env.user.has_group('base.group_system'):
            if any(vals.get(fname) for vals in vals_list for fname in PWF_ADMIN_FIELDS):
                raise AccessError(_("Only an Administrator can lock or unlock a project."))
        projects = super().create(vals_list)
        projects._pwf_evaluate_lock()
        return projects

    def write(self, vals):
        if self.env.context.get('pwf_lock_eval'):
            return super().write(vals)
        vals = dict(vals)
        self._pwf_check_lock_rights(vals)
        # Before anything is written. This class is registered after the
        # workflow class (models/__init__.py), so its write runs first and the
        # overdue reason is what the user sees, ahead of any stage-gate message.
        self._pwf_check_overdue_stage_change(vals)
        is_admin = self.env.su or self.env.user.has_group('base.group_system')
        if 'pwf_locked' in vals and not is_admin:
            # Unchanged (the rights check passed): a no-op from a non-admin
            # must not turn into a manual override.
            del vals['pwf_locked']
        if 'pwf_locked' in vals:
            # An explicit lock / unlock is an administrator override.
            if vals['pwf_locked']:
                vals.setdefault('pwf_manual_lock', True)
                vals.setdefault('pwf_manual_unlock', False)
            else:
                vals.setdefault('pwf_manual_lock', False)
                if any(project.pwf_locked for project in self):
                    vals.setdefault('pwf_manual_unlock', True)
        triggered = self._pwf_lock_triggered(vals)
        old_stages = ({project.id: project.stage_id for project in self}
                      if triggered else {})
        result = super().write(vals)
        if triggered:
            moved = self.filtered(
                lambda p: p.stage_id != old_stages.get(p.id)
                and p.pwf_manual_unlock)
            if moved:
                # The admin unlock override lasts until the stage changes.
                moved.sudo().with_context(pwf_lock_eval=True).write(
                    {'pwf_manual_unlock': False})
            self._pwf_evaluate_lock()
        return result

    # ------------------------------------------------------------------
    # Cron
    # ------------------------------------------------------------------
    @api.model
    def _cron_pwf_evaluate_locks(self):
        """Daily: lock projects that became overdue, unlock the ones whose
        lock reasons have cleared."""
        projects = self.sudo().search([])
        to_lock, to_unlock = projects._pwf_evaluate_lock()
        if to_lock or to_unlock:
            _logger.info("PMS workflow: locked %s and unlocked %s project(s).",
                         len(to_lock), len(to_unlock))
        return True

    @api.model
    def _cron_pwf_lock_overdue_projects(self):
        """Former cron entry point, kept for existing ir.cron records."""
        return self._cron_pwf_evaluate_locks()
