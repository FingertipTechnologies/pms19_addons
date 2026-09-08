import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# Project Type -> the stage-applicability flag on project.project.stage.
#
# The Project Type field itself lives in bt_project_customization as
# `ft_project_type`, NOT here. This module used to declare its own
# `project_type` defaulting to 'general', which would have re-labelled all 299
# existing projects as General on install and left somebody to reclassify them
# by hand. bt_project_customization's field is already populated and verified
# (219 Implementation / 54 AMC / 26 General), so this module reads it instead
# of competing with it. The keys below are that field's stored values.
TYPE_STAGE_FLAG = {
    'general': 'pl_for_general',
    'implementation': 'pl_for_implementation',
    'amc': 'pl_for_amc',
}


class ProjectProject(models.Model):
    _inherit = 'project.project'

    # --- Milestone dates ----------------------------------------------------
    # Only the dates the existing PMS "Dates" group does NOT already carry.
    # Regression and Training now reuse bt_project_customization's
    # ft_regression_date/ft_training_date (added there for the Stage
    # Validation Framework, after this list was first written) instead of
    # duplicating them under a second label — a stage-validation error against
    # ft_regression_date otherwise looked unfixable while a same-labelled
    # pl_regression_date sat filled in right above it. The others (Start,
    # Kick-off, BRD Approval, Sandbox Review, UAT Start, Support Start) reuse
    # the bt_project_customization fields shown there, and Closed Date reuses
    # the core `date` (End Date), relabelled in the form.
    pl_data_upload_date = fields.Date(string='Data Upload Date')
    pl_support_end_date = fields.Date(string='Support End Date')
    # Stamped by _pl_stamp_lifecycle_dates when the project is put on hold, and
    # cleared when it comes off. Cleared rather than kept, so the date always
    # describes the hold currently in force: a project parked, resumed and
    # parked again would otherwise still be showing last year's date. The
    # chatter keeps the history, because pl_on_hold is tracked.
    pl_hold_date = fields.Date(string='Hold Date')

    # Parked, as a flag rather than a stage.
    #
    # HOLD used to be a stage every Project Type could reach, which meant
    # parking a project destroyed the one thing worth knowing when it came
    # back: the stage it was parked FROM. "In DEV" and "on hold" are answers to
    # two different questions and a single stage_id can only hold one of them,
    # so a project resumed after three months had to have its old stage
    # reconstructed from chatter by hand.
    #
    # As a boolean the two coexist. A project sits in DEV and is on hold; it
    # comes off hold still in DEV, with nothing to reconstruct. It also means
    # every hold is visible as a filterable column rather than being spread
    # across whichever stage happens to be folded.
    pl_on_hold = fields.Boolean(
        string='On Hold',
        tracking=True,
        help="Park the project without taking it out of its workflow. The "
             "stage goes on saying how far the work had got; this says it is "
             "paused.",
    )

    # Stages the current Project Type is allowed to MOVE TO. Feeds the
    # constraint below, and nothing else — the form reads the field under it.
    pl_allowed_stage_ids = fields.Many2many(
        'project.project.stage',
        string='Allowed Stages',
        compute='_compute_pl_allowed_stage_ids',
    )

    # The same list plus the project's OWN current stage, which is what the
    # status bar offers.
    #
    # The two differ for one reason, and it is the reason DISC and DEV used to
    # appear on every General project's status bar. A handful of projects stand
    # on a stage their type's workflow does not contain — archived internal
    # work left in Development, a project whose type was corrected after the
    # fact — and they have to stay saveable. That used to be arranged by giving
    # the STAGE the extra type flag (see _apply_stage_flags in hooks.py), which
    # is a per-stage answer to a per-project problem: two archived projects in
    # Development put the whole Implementation pipeline on the status bar of all
    # 26 General projects.
    #
    # Adding the exception to the PROJECT instead keeps it to the project that
    # needs it. A General project in DEV goes on showing DEV, because that is
    # where it is; every other General project sees the General workflow only.
    #
    # The constraint deliberately does NOT read this field. If it did, stage_id
    # would always be in its own allowed list and the check could never fail.
    # Its job is to validate a stage being moved TO; showing where a project
    # already is is the form's.
    pl_selectable_stage_ids = fields.Many2many(
        'project.project.stage',
        string='Selectable Stages',
        compute='_compute_pl_allowed_stage_ids',
    )

    @api.depends('ft_project_type', 'stage_id')
    def _compute_pl_allowed_stage_ids(self):
        Stage = self.env['project.project.stage'].sudo()
        # One search per type for the whole recordset; the compute runs for every
        # row of the project list.
        stages_by_type = {
            ptype: Stage.search([(flag, '=', True)])
            for ptype, flag in TYPE_STAGE_FLAG.items()
        }
        all_stages = Stage.search([])
        for project in self:
            allowed = stages_by_type.get(project.ft_project_type, all_stages)
            project.pl_allowed_stage_ids = allowed
            project.pl_selectable_stage_ids = allowed | project.stage_id

    @api.model
    def _pl_allowed_stages_for_type(self, ptype):
        """Stages (sequence order) a Project Type may use; all if unknown type."""
        Stage = self.env['project.project.stage'].sudo()
        flag = TYPE_STAGE_FLAG.get(ptype)
        domain = [(flag, '=', True)] if flag else []
        return Stage.search(domain, order='sequence, id')

    # Which stage columns the Projects Kanban draws.
    #
    # Core expands them with _read_group_expand_full, which returns every ACTIVE
    # stage regardless of whether anything is in it. That is the right default
    # for a pipeline whose stages are all live, and the wrong one here, because
    # this module retires the stages it replaces rather than deleting them, and
    # a stage that has been drained but not yet archived would otherwise keep an
    # empty column on the board forever — with no way to clear it from the UI,
    # since archiving a stage by hand strands whatever is still on it.
    #
    # So: expand a stage if it belongs to a lifecycle (any pl_for_* flag) or if
    # it still holds at least one project. The first half keeps the real
    # pipeline visible even where a stage is legitimately empty — an empty DEV
    # column is information. The second half is the safety property: a stage is
    # never dropped from the board while anything is on it, so no project can
    # be hidden by this, including projects on a stage that has already been
    # archived. A legacy stage disappears by itself the moment it is drained,
    # and comes back on its own if a project ever lands on it again.
    stage_id = fields.Many2one(group_expand='_pl_read_group_stage_ids')

    @api.model
    def _pl_read_group_stage_ids(self, stages, domain):
        """Stages to show as Kanban columns: the lifecycle's, plus any occupied one.

        `domain` is ignored, as it is in core's _read_group_expand_full: the
        columns describe the pipeline, not the filter currently applied to it,
        so narrowing the search must not make stages vanish from the board.
        """
        lifecycle = stages.search([
            '|', '|',
            ('pl_for_implementation', '=', True),
            ('pl_for_general', '=', True),
            ('pl_for_amc', '=', True),
        ])
        # active_test=False so an archived project cannot be the reason its
        # stage silently loses its column, and sudo() so a user whose record
        # rules hide a project still sees a board with the same shape as
        # everyone else's.
        occupied = stages.browse([
            group[0].id
            for group in self.with_context(active_test=False).sudo()._read_group(
                [('stage_id', '!=', False)], groupby=['stage_id'])
            if group[0]
        ])
        return (lifecycle | occupied).sorted(lambda s: (s.sequence or 0, s.id))

    # NB: no @api.onchange on ft_project_type. Assigning a tracked field (stage_id)
    # on an unsaved record trips Odoo's duration-tracking mixin (it builds a Json
    # keyed by the record's NewId and crashes). The stage is kept valid for the
    # type in create()/write() instead, where records have real ids.

    @api.constrains('stage_id', 'ft_project_type')
    def _check_stage_for_type(self):
        for project in self:
            if not project.ft_project_type or not project.stage_id:
                continue
            if project.stage_id not in project.pl_allowed_stage_ids:
                raise ValidationError(_(
                    "Stage '%(stage)s' is not part of the %(type)s workflow.",
                    stage=project.stage_id.name,
                    type=dict(project._fields['ft_project_type'].selection)
                    .get(project.ft_project_type, project.ft_project_type),
                ))

    @api.model
    def _pl_repair_type_stage_mismatches(self):
        """Ops entry point for the reconciler that runs on install and upgrade.

        The same function ``migrations/0.0.0/post-migrate.py`` calls, exposed on
        the model so it can be run against a staging or live database from
        ``odoo shell`` without shipping code, e.g. after a restore or a hand-run
        UPDATE on ft_project_type::

            env['project.project']._pl_repair_type_stage_mismatches()
            env.cr.commit()

        Imported inside the method because hooks.py imports TYPE_STAGE_FLAG from
        this module; at module level the two would import each other.
        """
        from ..hooks import repair_type_stage_mismatches
        return repair_type_stage_mismatches(self.env)

    @api.model
    def _pl_finish_stage_migration(self):
        """Ops entry point for the old-pipeline stage move, alongside the two below.

        Needed because the automatic paths both have a gate that a real database
        can fall between:

        * ``post_init_hook`` runs the move at INSTALL, which is too early if the
          Project Types are not all filled in yet — an untyped project matches no
          stage mapping, so it stays on the old pipeline and the old stages
          are all kept active rather than retired.
        * ``migrations/0.0.0`` runs it again on a version CHANGE, which does not
          happen if the module was installed fresh at the current version. That
          is exactly the case after installing this module and upgrading
          bt_project_customization in the same run, or in either order: the types
          get fixed, the stages do not, and no later ``-u`` will retry it because
          the installed version already matches the manifest.

        So, from ``odoo shell``, once the types are right::

            env['project.project']._pl_finish_stage_migration()
            env.cr.commit()

        Idempotent, and it reports what it found either way. Imported inside the
        method for the same circular-import reason as the two below.
        """
        from ..hooks import (
            adopt_legacy_stages,
            legacy_pipeline_debris,
            repair_type_stage_mismatches,
        )
        stages, projects = legacy_pipeline_debris(self.env.cr)
        _logger.info(
            "ft_project_lifecycle: %s project(s) on %s unadopted stage(s); "
            "adopting the existing stages into the lifecycle.", projects, stages)
        # Same order as post_init_hook and the 0.0.0 migration. Adoption renames
        # the stages in place, so this is safe to run on a database whose
        # projects must not move.
        moved = adopt_legacy_stages(self.env)
        repair_type_stage_mismatches(self.env)
        return moved

    @api.model
    def _pl_backfill_start_dates(self):
        """Ops entry point for the Start Date backfill, alongside the stage
        reconciler above.

        Fills Start Date from the creation date on every project that has none.
        Runs on install and on every upgrade; exposed here so it can also be run
        by hand from ``odoo shell`` after fixing an End Date the backfill
        refused to write past::

            env['project.project']._pl_backfill_start_dates()
            env.cr.commit()

        Imported inside the method for the same circular-import reason as
        _pl_repair_type_stage_mismatches.
        """
        from ..hooks import backfill_start_dates
        return backfill_start_dates(self.env)

    def _pl_stamp_lifecycle_dates(self):
        """Stamp Closed Date from the stage, Hold Date from the On Hold flag."""
        today = fields.Date.context_today(self)
        closed = self.env.ref(
            'ft_project_lifecycle.stage_closed', raise_if_not_found=False)
        for project in self:
            updates = {}
            # `date` is the core End Date, surfaced as Closed Date (see #10).
            if closed and project.stage_id == closed and not project.date:
                updates['date'] = today
            # Hold Date follows pl_on_hold in both directions. Clearing it on
            # the way out is what lets the next hold stamp a fresh date instead
            # of silently keeping the previous one.
            if project.pl_on_hold and not project.pl_hold_date:
                updates['pl_hold_date'] = today
            elif not project.pl_on_hold and project.pl_hold_date:
                updates['pl_hold_date'] = False
            if updates:
                super(ProjectProject, project).write(updates)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Start Date defaults to the creation date for every new project.
            if not vals.get('date_start'):
                vals['date_start'] = fields.Date.context_today(self)
            # Force a stage valid for the Project Type: use the given one when it
            # already fits, otherwise fall back to the type's first stage.
            #
            # ft_project_type carries no default any more — it is chosen on the
            # creation form — so a create can reach here with none. Two cases,
            # and neither may guess a stage:
            #   * a person creating from a form is about to be told the field is
            #     required, so any stage picked here is thrown away with the
            #     record;
            #   * a sudo'd server-side create (module install, migrations,
            #     hr_timesheet's "Internal" project, sale_timesheet's
            #     project-from-sale-order) has bt_project_customization's
            #     create() stamping FT_FALLBACK_PROJECT_TYPE — but one step DOWN
            #     the MRO, because this module is loaded after it and so runs
            #     first. Resolving the same fallback here is what keeps the two
            #     in step; reading it from default_get, as this used to, now
            #     returns nothing and would home the project against every stage
            #     in the database, only for _check_stage_for_type to reject the
            #     stage as belonging to another pipeline.
            ptype = vals.get('ft_project_type')
            if not ptype and self.env.su:
                ptype = self.FT_FALLBACK_PROJECT_TYPE
            if ptype:
                allowed = self._pl_allowed_stages_for_type(ptype)
                if allowed and vals.get('stage_id') not in allowed.ids:
                    vals['stage_id'] = allowed[0].id
        projects = super().create(vals_list)
        projects._pl_stamp_lifecycle_dates()
        return projects

    def write(self, vals):
        # An Implementation project must never be converted to AMC; a fresh AMC
        # project is created instead.
        if vals.get('ft_project_type') == 'amc':
            offending = self.filtered(
                lambda p: p.ft_project_type == 'implementation')
            if offending:
                raise UserError(_(
                    "An Implementation project cannot be moved to AMC. Please "
                    "create a new project with Project Type = AMC instead."))

        # Changing the type can strand a project on a stage the new type does
        # not run. The stage has to move in the SAME write, not after it:
        # super().write() calls _validate_fields before it returns (see
        # odoo/orm/models.py), so _check_stage_for_type fires on the half-updated
        # record and raises "Stage 'Working' is not part of the Implementation
        # workflow" — the user sees an error where the intent was to re-home the
        # project automatically. Fixing the stage after super() cannot work for
        # the only case it would ever be needed in.
        #
        # Only the records that actually need it are re-homed, so a project
        # already on a shared stage (CLOSED) keeps its place. The recursive
        # calls terminate: the stranded half is rewritten with stage_id set,
        # which skips this branch, and the remaining half has nothing stranded.
        new_type = vals.get('ft_project_type')
        if new_type and 'stage_id' not in vals:
            allowed = self._pl_allowed_stages_for_type(new_type)
            if allowed:
                stranded = self.filtered(
                    lambda p: p.stage_id and p.stage_id not in allowed)
                if stranded:
                    stranded.write(dict(vals, stage_id=allowed[0].id))
                    remainder = self - stranded
                    if remainder:
                        remainder.write(vals)
                    return True

        res = super().write(vals)
        if 'stage_id' in vals or 'pl_on_hold' in vals:
            self._pl_stamp_lifecycle_dates()
        return res
