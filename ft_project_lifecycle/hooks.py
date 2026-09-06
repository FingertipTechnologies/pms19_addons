import logging

from odoo import fields

from .models.project_project import TYPE_STAGE_FLAG

_logger = logging.getLogger(__name__)

# Where each project already sitting in the OLD pipeline lands in the new one,
# keyed by (Project Type, old stage name lower-cased) -> new stage xmlid.
#
# Keyed by TYPE as well as by stage, which the previous version of this hook was
# not: it mapped "To Do" to DISC for everybody. DISC is Implementation-only, so
# that would have dropped General and AMC projects into a stage their own type
# is not allowed to use, and the very next save of one would have raised
# "Stage 'DISC' is not part of the General workflow".
#
# Old stage names are matched lower-cased at the 'en_US' key because the stage
# name is a translated jsonb column.
_STAGE_MAP = {
    'implementation': {
        # The old pipeline maps one-for-one onto the new lifecycle, except
        # where two old stages collapse into one new one.
        'discovery': 'stage_disc',
        'to do': 'stage_disc',
        'development': 'stage_dev',
        'in progress': 'stage_dev',
        'production testing': 'stage_reg',
        # Sandbox Review and Sandbox Testing were two names for the same step.
        'sandbox review': 'stage_srv',
        'sandbox testing': 'stage_srv',
        'user acceptance': 'stage_uat',
        'data upload': 'stage_data',
        # Deployment has no counterpart in the new lifecycle. It sat directly
        # after User Acceptance in the old sequence, and DATA is what directly
        # follows UAT in the new one, so that is where it goes. One project.
        'deployment': 'stage_data',
        'training': 'stage_tra',
        'support': 'stage_support',
        'hold': 'stage_hold',
        'closed': 'stage_closed',
        'done': 'stage_closed',
        'cancelled': 'stage_closed',
        'canceled': 'stage_closed',
    },
    # AMC and General share one three-stage workflow, so they share one mapping
    # shape: anything mid-flight becomes Working, anything not yet begun
    # becomes Started, anything finished becomes Completed.
    #
    # 'hold' still routes to stage_hold in all three maps, and that is on
    # purpose even though HOLD is no longer a stage anyone can select: it is a
    # waypoint. move_hold_stage_to_flag runs straight after this and collects
    # everything sitting on stage_hold, so routing here keeps parked projects
    # identifiable for exactly as long as it takes to convert them to the
    # pl_on_hold flag. Flattening them into Working here instead would lose the
    # parked/working distinction before anything could record it.
    'amc': {
        'discovery': 'stage_started',
        'to do': 'stage_started',
        'general': 'stage_started',
        'amc': 'stage_working',
        'development': 'stage_working',
        'in progress': 'stage_working',
        'support': 'stage_working',
        'closed': 'stage_completed',
        'done': 'stage_completed',
        'cancelled': 'stage_completed',
        'canceled': 'stage_completed',
        'hold': 'stage_hold',
    },
    'general': {
        'discovery': 'stage_started',
        'to do': 'stage_started',
        'general': 'stage_working',
        'development': 'stage_working',
        'in progress': 'stage_working',
        'support': 'stage_working',
        'amc': 'stage_working',
        'closed': 'stage_completed',
        'done': 'stage_completed',
        'cancelled': 'stage_completed',
        'canceled': 'stage_completed',
        'hold': 'stage_hold',
    },
}

# Used only if a stage turns up that _STAGE_MAP has never heard of. Every stage
# on the database at the time of writing is mapped explicitly above, so landing
# here means somebody added a stage since; it is logged as a warning naming the
# projects, never applied silently.
_FALLBACK = {
    'implementation': 'stage_dev',
    'amc': 'stage_working',
    'general': 'stage_working',
}

_BACKUP_TABLE = 'ft_pl_stage_backup'
_REPAIR_TABLE = 'ft_pl_repair_log'


def backfill_start_dates(env):
    """Populate Start Date from the creation date for projects that have none.

    Written in SQL, and that is the whole point of this function rather than an
    incidental optimisation. ``project.project.write`` treats date_start and
    date (End Date) as a PAIR and silently drops half of it::

        date_start = vals.get('date_start', True)
        date_end = vals.get('date', True)
        ...
        if (date_start_update and no_current_date_end and not date_end_update):
            del vals['date_start']

    Read that against what this function does: it writes date_start on its own,
    to projects whose date_start is empty — and the projects it is for have no
    End Date either. So every condition holds, ``vals`` comes out empty, core's
    ``super().write(vals) if vals else True`` writes nothing, and the ORM
    version of this backfill silently populated NOTHING while reporting success.
    That is why projects created months ago still show an empty Start Date.

    Setting date and date_start together is not an option: an End Date is a
    commitment somebody makes, not something a backfill may invent.

    ``create_date::date`` reproduces what fields.Date.to_date(create_date) gave
    — the UTC calendar date, not the user's — so re-running this over rows an
    earlier version did manage to fill changes nothing.

    The WHERE clause also guards _project_date_greater ("check(date >=
    date_start)"): a project whose End Date predates its creation would fail the
    constraint and abort the whole upgrade, so it is left alone and logged.
    Idempotent, so it is safe on every upgrade forever.
    """
    env.cr.execute("""
        UPDATE project_project
           SET date_start = create_date::date
         WHERE date_start IS NULL
           AND create_date IS NOT NULL
           AND (date IS NULL OR date >= create_date::date)
    """)
    filled = env.cr.rowcount
    env.cr.execute("""
        SELECT id FROM project_project
         WHERE date_start IS NULL AND create_date IS NOT NULL
    """)
    skipped = [row[0] for row in env.cr.fetchall()]
    # Written behind the ORM's back, so anything already loaded still holds the
    # old NULL.
    env['project.project'].invalidate_model(['date_start'])
    _logger.info(
        "ft_project_lifecycle: filled Start Date from the creation date on %s "
        "project(s).", filled)
    if skipped:
        _logger.warning(
            "ft_project_lifecycle: %s project(s) left without a Start Date "
            "because their End Date precedes their creation date: %s. Fix the "
            "End Date and re-run "
            "env['project.project']._pl_backfill_start_dates().",
            len(skipped), skipped)
    return filled


def _snapshot_stages(env):
    """Record every project's stage before it is touched, so this is reversible.

    A permanent table rather than a temporary one: it is the audit trail for a
    move that rewrites the stage of every project on the database, and it makes
    the whole migration undoable with a single UPDATE ... FROM if the mapping
    turns out to be wrong for some project nobody checked.
    """
    env.cr.execute("""
        CREATE TABLE IF NOT EXISTS %s (
            project_id      integer PRIMARY KEY,
            project_name    text,
            project_type    varchar,
            old_stage_id    integer,
            old_stage_name  text,
            new_stage_id    integer,
            migrated_at     timestamp DEFAULT now()
        )
    """ % _BACKUP_TABLE)
    env.cr.execute("""
        INSERT INTO %s (project_id, project_name, project_type,
                        old_stage_id, old_stage_name)
        SELECT p.id, p.name->>'en_US', p.ft_project_type,
               p.stage_id, s.name->>'en_US'
          FROM project_project p
          LEFT JOIN project_project_stage s ON p.stage_id = s.id
         ON CONFLICT (project_id) DO NOTHING
    """ % _BACKUP_TABLE)
    return env.cr.rowcount


def migrate_existing_stages(env):
    """Move every existing project from the old pipeline onto the new stages.

    Raw SQL throughout, for three separate reasons:

    1. ``_check_stage_for_type`` would fire on an ORM write. Mid-migration, a
       project's stage and its type's allowed stages disagree by definition —
       that is the state being repaired — so the constraint would abort the very
       write that fixes it.
    2. ``stage_id`` is tracked, so an ORM write would post a chatter message and
       a mail.tracking row on all 299 projects.
    3. Archiving a project stage through the ORM cascades: core's write pulls
       the projects sitting in it down with it. The stages are emptied first and
       archived in SQL second, so nothing can be dragged along even in
       principle.

    Nothing is deleted. The old stages are archived, never dropped: 20,595
    timesheet lines hold a frozen `project_status` pointing at them, and
    deleting the stages would destroy that history.
    """
    snapshotted = _snapshot_stages(env)

    # Resolve the new stages once. A missing xmlid means the data file did not
    # load, in which case migrating would move projects onto nothing.
    def stage_id(xmlid):
        rec = env.ref('ft_project_lifecycle.%s' % xmlid, raise_if_not_found=False)
        return rec.id if rec else None

    new_ids = {name: stage_id(name) for name in set(
        list(_FALLBACK.values())
        + [x for m in _STAGE_MAP.values() for x in m.values()]
    )}
    missing = [k for k, v in new_ids.items() if not v]
    if missing:
        _logger.error(
            "ft_project_lifecycle: stage records missing (%s); "
            "stage migration skipped, projects left where they are.",
            ', '.join(sorted(missing)))
        return

    # The old stages, i.e. everything that is not one of the new ones.
    env.cr.execute(
        "SELECT id, lower(trim(name->>'en_US')) FROM project_project_stage "
        "WHERE id NOT IN %s",
        (tuple(new_ids.values()),))
    old_stages = dict(env.cr.fetchall())

    moved = 0
    for ptype, mapping in _STAGE_MAP.items():
        for old_id, old_name in old_stages.items():
            target = mapping.get(old_name)
            if not target:
                env.cr.execute(
                    "SELECT name->>'en_US' FROM project_project "
                    "WHERE stage_id = %s AND ft_project_type = %s",
                    (old_id, ptype))
                stranded = [r[0] for r in env.cr.fetchall()]
                if not stranded:
                    continue
                target = _FALLBACK[ptype]
                _logger.warning(
                    "ft_project_lifecycle: stage '%s' is not in the %s mapping; "
                    "falling back to %s for %s project(s): %s",
                    old_name, ptype, target, len(stranded),
                    ', '.join(stranded))
            env.cr.execute(
                "UPDATE project_project SET stage_id = %s "
                " WHERE stage_id = %s AND ft_project_type = %s",
                (new_ids[target], old_id, ptype))
            moved += env.cr.rowcount

    env.cr.execute("""
        UPDATE %s b SET new_stage_id = p.stage_id
          FROM project_project p WHERE p.id = b.project_id
    """ % _BACKUP_TABLE)

    # Only now, with the old stages provably empty, retire them.
    env.cr.execute(
        "SELECT count(*) FROM project_project WHERE stage_id IN %s",
        (tuple(old_stages) or (0,),))
    left_behind = env.cr.fetchone()[0]
    if left_behind:
        _logger.error(
            "ft_project_lifecycle: %s project(s) still on old stages; "
            "leaving the old stages active so nothing is stranded.",
            left_behind)
    else:
        env.cr.execute(
            "UPDATE project_project_stage SET active = false WHERE id IN %s",
            (tuple(old_stages) or (0,),))

    # The rows were changed underneath the ORM; drop what it thinks it knows.
    env.invalidate_all()
    _logger.info(
        "ft_project_lifecycle: snapshotted %s project(s), moved %s onto the "
        "new stages, archived %s old stage(s).",
        snapshotted, moved, 0 if left_behind else len(old_stages))


def _pre_hold_stages(cr, project_ids):
    """{project_id: (stage name it was parked FROM, date it was parked)}.

    Read out of the chatter. When HOLD was a stage, moving a project onto it
    overwrote the stage it came from — that is precisely the loss this whole
    change is undoing — so the only surviving record of where a parked project
    belongs is the tracking row written at the time. DISTINCT ON with a
    descending date takes the most recent parking, since a project can have been
    parked, resumed and parked again.

    Names come back lower-cased and are OLD pipeline names ('deployment',
    'user acceptance'); the caller maps them through _STAGE_MAP.
    """
    if not project_ids:
        return {}
    cr.execute(
        """
        SELECT DISTINCT ON (m.res_id)
               m.res_id, lower(trim(t.old_value_char)), m.date::date
          FROM mail_tracking_value t
          JOIN mail_message m ON m.id = t.mail_message_id
          JOIN ir_model_fields f ON f.id = t.field_id
         WHERE m.model = 'project.project'
           AND f.model = 'project.project'
           AND f.name = 'stage_id'
           AND m.res_id IN %s
           AND lower(trim(t.new_value_char)) = 'hold'
         ORDER BY m.res_id, m.date DESC
        """,
        (tuple(project_ids),))
    return {r[0]: (r[1], r[2]) for r in cr.fetchall()}


def move_hold_stage_to_flag(env):
    """Retire the HOLD stage in favour of the pl_on_hold flag.

    Being parked stopped being a stage and became a checkbox, because a stage
    could only ever hold one answer: putting a project on HOLD overwrote the
    stage it was working in, so resuming it meant somebody reconstructing that
    from chatter by hand. The flag sits beside stage_id, so a project is "in DEV
    and parked" and comes back to DEV on its own.

    Each parked project therefore needs a stage to land on, best-effort in this
    order:

    1. The stage the chatter says it was parked FROM, either named directly (a
       project parked after the lifecycle stages went live) or mapped through
       _STAGE_MAP from an old pipeline name. Right for 11 of the 19 parked
       projects on the database this was written against.
    2. Its Project Type's first stage, for the rest — the ones parked before
       tracking, or by an earlier SQL migration that wrote no chatter. It loses
       their place in the flow, which is why it is the fallback and why every
       one of them is named in the log.

    The stage record itself is archived and stripped of its three type flags,
    never deleted: seven tables carry a foreign key to project.project.stage,
    including the frozen project_status on ~20,000 timesheet lines.

    Idempotent. Once the stage is empty and archived there is nothing to find,
    and it logs one line saying so.
    """
    cr = env.cr
    hold = env.ref('ft_project_lifecycle.stage_hold', raise_if_not_found=False)
    if not hold:
        _logger.info(
            "ft_project_lifecycle: no HOLD stage record; nothing to retire.")
        return 0

    # Raw SQL so archived projects are included, and so nothing trips
    # _check_stage_for_type mid-move — HOLD is invalid for every type by the
    # time the projects are shifted, which is the state being repaired.
    cr.execute(
        "SELECT id, ft_project_type, name->>'en_US' "
        "  FROM project_project WHERE stage_id = %s ORDER BY id",
        (hold.id,))
    parked = cr.fetchall()

    pre_hold = _pre_hold_stages(cr, [r[0] for r in parked])

    # Flags off and archived FIRST, so the allowed-stage lookup below cannot
    # offer HOLD back as a landing place for the very projects leaving it.
    cr.execute(
        "UPDATE project_project_stage "
        "   SET active = false, pl_for_implementation = false, "
        "       pl_for_general = false, pl_for_amc = false "
        " WHERE id = %s",
        (hold.id,))
    env.invalidate_all()

    if not parked:
        _logger.info(
            "ft_project_lifecycle: HOLD stage already empty; archived, "
            "nothing to move.")
        return 0

    Project = env['project.project']
    Stage = env['project.project.stage'].sudo()

    # The live lifecycle stages by lower-cased name, for a tracked value that
    # already names one of them. Keyed off the type flags rather than off
    # `active`, so the archived OLD pipeline stages cannot be landed on.
    lifecycle_by_name = {}
    for st in Stage.search([
            '|', '|',
            ('pl_for_implementation', '=', True),
            ('pl_for_general', '=', True),
            ('pl_for_amc', '=', True)]):
        lifecycle_by_name.setdefault((st.name or '').strip().lower(), st)

    allowed_by_type = {
        ptype: Project._pl_allowed_stages_for_type(ptype)
        for ptype in TYPE_STAGE_FLAG
    }

    def _target(ptype, old_name):
        """(stage id, how it was chosen) for a project parked from `old_name`."""
        allowed = allowed_by_type.get(ptype) or Stage.browse()
        if old_name and old_name != 'hold':
            direct = lifecycle_by_name.get(old_name)
            if direct and direct in allowed:
                return direct.id, 'tracked'
            xmlid = _STAGE_MAP.get(ptype, {}).get(old_name)
            mapped = env.ref('ft_project_lifecycle.%s' % xmlid,
                             raise_if_not_found=False) if xmlid else None
            if mapped and mapped in allowed:
                return mapped.id, 'mapped'
        return (allowed[0].id if allowed else None), 'fallback'

    today = fields.Date.context_today(Project)
    moved, guessed = 0, []
    for pid, ptype, pname in parked:
        old_name, hold_date = pre_hold.get(pid, (None, None))
        target, how = _target(ptype, old_name)
        if not target:
            _logger.error(
                "ft_project_lifecycle: Project Type '%s' has no stage to move "
                "parked project %s '%s' onto; left on HOLD.", ptype, pid, pname)
            continue
        cr.execute(
            "UPDATE project_project "
            "   SET stage_id = %s, pl_on_hold = TRUE, "
            "       pl_hold_date = COALESCE(pl_hold_date, %s) "
            " WHERE id = %s",
            (target, hold_date or today, pid))
        moved += 1
        if how == 'fallback':
            guessed.append('%s %r' % (pid, pname))

    env.invalidate_all()

    if guessed:
        _logger.warning(
            "ft_project_lifecycle: %s parked project(s) had no record of the "
            "stage they were parked from and were put on their Project Type's "
            "first stage: %s.", len(guessed), ', '.join(guessed))

    cr.execute(
        "SELECT count(*) FROM project_project WHERE stage_id = %s", (hold.id,))
    left = cr.fetchone()[0]
    if left:
        _logger.error(
            "ft_project_lifecycle: %s project(s) still on the HOLD stage after "
            "the move; it has been archived and they cannot be saved until "
            "they are re-staged by hand.", left)
    else:
        _logger.info(
            "ft_project_lifecycle: retired the HOLD stage — %s project(s) "
            "marked On Hold and moved back onto their workflow (%s recovered "
            "from chatter, %s defaulted); stage archived.",
            moved, moved - len(guessed), len(guessed))
    return moved


def _stage_allows_type_sql(type_expr, stage_alias='s'):
    """SQL boolean: does the stage aliased `stage_alias` allow type `type_expr`?

    Built from TYPE_STAGE_FLAG rather than spelled out, so it cannot drift from
    the model's own idea of which pl_for_* flag belongs to which Project Type.

    An unrecognised type yields TRUE, matching the "no opinion" that
    _pl_allowed_stages_for_type takes for a type this module has never heard of.
    A project on a type nobody has taught us about is left exactly where it is
    rather than being "repaired" onto a guess.

    Returns (sql, params); the params are the type values for the CASE arms and
    must be passed at the position the fragment is interpolated into.
    """
    items = sorted(TYPE_STAGE_FLAG.items())
    whens = ' '.join(
        "WHEN %s THEN COALESCE({0}.{1}, FALSE)".format(stage_alias, flag)
        for _ptype, flag in items
    )
    sql = "(CASE {0} {1} ELSE TRUE END)".format(type_expr, whens)
    return sql, [ptype for ptype, _flag in items]


def _broken_project_ids(cr):
    """Projects sitting on a stage their own Project Type is not allowed to use."""
    allows, params = _stage_allows_type_sql('p.ft_project_type')
    cr.execute(
        """
        SELECT p.id
          FROM project_project p
          JOIN project_project_stage s ON s.id = p.stage_id
         WHERE p.ft_project_type IS NOT NULL
           AND NOT %s
         ORDER BY p.id
        """ % allows,
        params,
    )
    return [r[0] for r in cr.fetchall()]


def _project_state(cr, ids):
    """(type, stage_id, name) for each id, keyed by id."""
    if not ids:
        return {}
    cr.execute(
        "SELECT id, ft_project_type, stage_id, name->>'en_US' "
        "  FROM project_project WHERE id IN %s",
        (tuple(ids),))
    return {r[0]: (r[1], r[2], r[3]) for r in cr.fetchall()}


def repair_type_stage_mismatches(env):
    """Put every project back on a stage its own Project Type is allowed to use.

    A project whose stage and type disagree is not a cosmetic problem: the
    _check_stage_for_type constraint fires on the next save of that project, so
    the record becomes uneditable until somebody notices why. The pairing can
    drift whenever ft_project_type is changed outside the ORM — a classification
    migration re-running, a restore, a hand-run UPDATE — because none of those
    go through write(), which is what normally snaps the stage to match.

    Idempotent by construction: it reads the current mismatches, fixes them, and
    re-reads. Running it on a healthy database does nothing and logs one line,
    which is why it is safe to call on every install and every upgrade rather
    than pinning it to one version.

    Two repairs, tried in that order:

    1. Restore the TYPE from ft_pl_stage_backup. Preferred, because the backup
       records what the project was classified as at the moment the stage
       migration placed it, so the recorded type is what actually justified the
       stage. Applied only when the project has not moved since (its stage is
       still the new_stage_id the migration set) and the recorded type makes the
       current stage legal — i.e. only when the type is provably the half that
       drifted. Raw SQL, not write(): restoring a type of 'amc' through the ORM
       would hit the Implementation-to-AMC guard in write() and raise.
    2. Otherwise, snap the STAGE to the first stage of the project's type. The
       fallback for anything the backup cannot vouch for; it loses the project's
       position in its flow, so it is second and it is logged by name.

    Every change is recorded in the permanent ft_pl_repair_log table, in the
    manner of ft_pl_stage_backup, so a repair that gets something wrong can be
    seen and undone rather than having to be reconstructed.
    """
    cr = env.cr
    broken = _broken_project_ids(cr)
    if not broken:
        _logger.info(
            "ft_project_lifecycle: Project Type / stage check clean, "
            "nothing to repair.")
        return 0

    before = _project_state(cr, broken)

    cr.execute("""
        CREATE TABLE IF NOT EXISTS %s (
            id            serial PRIMARY KEY,
            project_id    integer,
            project_name  text,
            old_type      varchar,
            new_type      varchar,
            old_stage_id  integer,
            new_stage_id  integer,
            action        varchar,
            repaired_at   timestamp DEFAULT now()
        )
    """ % _REPAIR_TABLE)

    # --- 1. Restore the type from the pre-migration snapshot, where it vouches
    #        for the stage the project is actually on.
    cr.execute("SELECT to_regclass(%s)", (_BACKUP_TABLE,))
    if cr.fetchone()[0] is not None:
        allows_backup, params_backup = _stage_allows_type_sql('b.project_type')
        cr.execute(
            """
            UPDATE project_project p
               SET ft_project_type = b.project_type
              FROM %s b, project_project_stage s
             WHERE b.project_id = p.id
               AND s.id = p.stage_id
               AND p.id IN %%s
               AND b.project_type IS NOT NULL
               AND b.project_type <> p.ft_project_type
               AND b.new_stage_id = p.stage_id
               AND %s
            """ % (_BACKUP_TABLE, allows_backup),
            [tuple(broken)] + params_backup,
        )
    else:
        _logger.info(
            "ft_project_lifecycle: no %s table on this database; repairing by "
            "stage only.", _BACKUP_TABLE)

    # --- 2. Snap whatever is still mismatched onto its type's first stage.
    still_broken = _broken_project_ids(cr)
    if still_broken:
        Project = env['project.project']
        by_type = {}
        for pid in still_broken:
            cr.execute(
                "SELECT ft_project_type FROM project_project WHERE id = %s",
                (pid,))
            by_type.setdefault(cr.fetchone()[0], []).append(pid)
        for ptype, ids in by_type.items():
            allowed = Project._pl_allowed_stages_for_type(ptype)
            if not allowed:
                _logger.error(
                    "ft_project_lifecycle: Project Type '%s' has no allowed "
                    "stage at all; leaving %s project(s) where they are.",
                    ptype, len(ids))
                continue
            cr.execute(
                "UPDATE project_project SET stage_id = %s WHERE id IN %s",
                (allowed[0].id, tuple(ids)))

    # --- Record what moved, and confirm the database is clean.
    after = _project_state(cr, broken)
    rows = []
    for pid, (old_type, old_stage, name) in before.items():
        new_type, new_stage, _name = after.get(pid, (old_type, old_stage, name))
        if new_type == old_type and new_stage == old_stage:
            continue
        rows.append((
            pid, name, old_type, new_type, old_stage, new_stage,
            'type_restored' if new_type != old_type else 'stage_snapped',
        ))
    if rows:
        cr.executemany(
            "INSERT INTO %s (project_id, project_name, old_type, new_type, "
            "old_stage_id, new_stage_id, action) "
            "VALUES (%%s, %%s, %%s, %%s, %%s, %%s, %%s)" % _REPAIR_TABLE,
            rows)
        for pid, name, old_type, new_type, old_stage, new_stage, action in rows:
            _logger.info(
                "ft_project_lifecycle: repaired project %s '%s' by %s "
                "(type %s -> %s, stage %s -> %s).",
                pid, name, action, old_type, new_type, old_stage, new_stage)

    # The rows were changed underneath the ORM; drop what it thinks it knows.
    env.invalidate_all()

    left = _broken_project_ids(cr)
    if left:
        _logger.error(
            "ft_project_lifecycle: %s project(s) still on a stage their type "
            "disallows after repair: %s. These will raise on their next save.",
            len(left), left)
    else:
        _logger.info(
            "ft_project_lifecycle: repaired %s project(s); every project is now "
            "on a stage its Project Type allows.", len(rows))
    return len(rows)


def post_init_hook(env):
    # Stages first: it puts every project on a stage its own type allows, so
    # any ORM write that follows cannot trip _check_stage_for_type.
    migrate_existing_stages(env)
    backfill_start_dates(env)
    # Before the reconciler, not after: it empties and archives the HOLD stage,
    # and a project still sitting on HOLD is exactly the kind of type/stage
    # mismatch the reconciler would otherwise try to "fix" by guessing.
    move_hold_stage_to_flag(env)
    # Last word on the type/stage pairing. migrate_existing_stages only places
    # projects it recognises as being on an old stage; this catches anything it
    # left, and anything a re-run classification elsewhere has since knocked out
    # of step.
    repair_type_stage_mismatches(env)
