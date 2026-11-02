import logging
from collections import defaultdict

import pytz

from .models.project_project import PL_ACTUAL_DATE_FIELDS

_logger = logging.getLogger(__name__)


def _local_date(dt, tz):
    """Calendar date of the naive-UTC datetime ``dt`` in timezone ``tz``."""
    if not dt:
        return None
    return pytz.utc.localize(dt).astimezone(tz).date()


def backfill_actual_stage_dates(env):
    """Fill the empty pl_actual_*_date columns of every Implementation project
    from the history already in the database. Idempotent: a date that is
    already set is never changed (COALESCE), so re-running it is harmless.

    Three sources, in order:

    1. The chatter tracking of stage_id (mail.tracking.value rows whose
       new value is a stage): the EARLIEST message date per (project, stage
       key) is the day the project first entered that stage. Archived stages
       count too - the pre-lifecycle "Discovery" classifies to 'disc' like
       DISC does - so a project's history on the old pipeline is kept.
    2. The project's CURRENT stage, when no tracking row names it (created or
       imported straight into it, or tracking older than the retention): the
       latest stage-tracking date of the project, else its creation date.
    3. The first stage of the chain that existed before KICKOFF - DISC - when
       the project is on or past it and the date is still empty: the creation
       date. Nothing ever stamps KICKOFF from the creation date, because no
       existing project passed through a stage that did not exist.

    Message datetimes are UTC; they are read as calendar dates in the
    company's timezone (the user's, then UTC, when the company has none).
    """
    cr = env.cr
    env.flush_all()
    Project = env['project.project'].sudo().with_context(active_test=False)
    Stage = env['project.project.stage'].sudo().with_context(
        active_test=False, lang='en_US')
    projects = Project.search([('ft_project_type', '=', 'implementation')])
    if not projects:
        _logger.info("ft_project_stage_dates: no Implementation project to backfill.")
        return 0

    tz_name = (env.company.partner_id.tz or env.user.tz or 'UTC')
    try:
        tz = pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError:
        tz = pytz.utc

    stage_key = {stage.id: stage._ft_stage_key() for stage in Stage.search([])}
    sort_key = Stage._ft_stage_sort_key

    # --- 1. tracking rows: earliest entry per (project, stage key) ---------
    entered = defaultdict(dict)   # project id -> {field: date}
    latest = {}                   # project id -> latest stage-tracking datetime
    field = env['ir.model.fields'].sudo().search([
        ('model', '=', 'project.project'), ('name', '=', 'stage_id'),
    ], limit=1)
    if field:
        cr.execute("""
            SELECT m.res_id, v.new_value_integer, MIN(m.date), MAX(m.date)
              FROM mail_tracking_value v
              JOIN mail_message m ON m.id = v.mail_message_id
             WHERE v.field_id = %s
               AND m.model = 'project.project'
               AND m.res_id IN %s
               AND COALESCE(v.new_value_integer, 0) <> 0
             GROUP BY m.res_id, v.new_value_integer
        """, (field.id, tuple(projects.ids)))
        for res_id, stage_id, first_dt, last_dt in cr.fetchall():
            if last_dt and (res_id not in latest or last_dt > latest[res_id]):
                latest[res_id] = last_dt
            fname = PL_ACTUAL_DATE_FIELDS.get(stage_key.get(stage_id))
            if not fname:
                continue
            day = _local_date(first_dt, tz)
            current = entered[res_id].get(fname)
            if day and (not current or day < current):
                entered[res_id][fname] = day
    from_tracking = sum(len(v) for v in entered.values())

    # --- 2. the current stage, 3. the first pre-KICKOFF stage ---------------
    # Live stages only: the Project recordset above carries
    # active_test=False (archived projects count), which the stage search
    # inside _pl_allowed_stages_for_type would otherwise inherit.
    chain = Project.with_context(active_test=True)._pl_allowed_stages_for_type(
        'implementation')
    first_stage = next(
        (s for s in chain if stage_key.get(s.id) not in (False, 'kickoff')
         and PL_ACTUAL_DATE_FIELDS.get(stage_key.get(s.id))), None)
    first_field = PL_ACTUAL_DATE_FIELDS.get(stage_key.get(first_stage.id)) if first_stage else None
    from_current = from_create = 0
    for project in projects:
        updates = entered[project.id]
        created = _local_date(project.create_date, tz)
        if project.stage_id:
            fname = PL_ACTUAL_DATE_FIELDS.get(stage_key.get(project.stage_id.id))
            if fname and not project[fname] and fname not in updates:
                day = _local_date(latest.get(project.id), tz) or created
                if day:
                    updates[fname] = day
                    from_current += 1
            if (first_stage and first_field and not project[first_field]
                    and first_field not in updates and created
                    and sort_key(project.stage_id) >= sort_key(first_stage)):
                updates[first_field] = created
                from_create += 1

    # --- write: only where the column is still empty ------------------------
    touched = 0
    for project in projects:
        updates = {
            fname: day for fname, day in entered[project.id].items()
            if not project[fname]
        }
        if not updates:
            continue
        assignments = ', '.join(
            '%s = COALESCE(%s, %%s)' % (fname, fname) for fname in updates)
        cr.execute(
            'UPDATE project_project SET %s WHERE id = %%s' % assignments,
            tuple(updates.values()) + (project.id,))
        touched += 1
    Project.invalidate_model(list(PL_ACTUAL_DATE_FIELDS.values()))
    _logger.info(
        "ft_project_stage_dates: backfilled actual stage dates on %s of %s "
        "Implementation project(s): %s from the stage tracking, %s current "
        "stages without tracking, %s first stages from the creation date.",
        touched, len(projects), from_tracking, from_current, from_create)
    return touched


def post_init_hook(env):
    backfill_actual_stage_dates(env)
