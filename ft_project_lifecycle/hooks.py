import logging

from .models.project_project import TYPE_STAGE_FLAG

_logger = logging.getLogger(__name__)


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
    # Written behind the ORM's ,, back, so anything already loaded still holds the
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


def legacy_pipeline_debris(cr):
    """(active legacy stages, projects still on one) — what is left of the old pipeline.

    An unadopted stage is one carrying none of the three pl_for_* flags:
    adoption sets at least one on every stage it touches, so the flags are what
    separate a stage that is part of the lifecycle from one that predates it.
    That definition is read off the module's own flags rather than a hard-coded
    name list, so a stage somebody added by hand is judged the same way as the
    ones shipped here.

    Reported rather than acted on. adopt_legacy_stages runs regardless and is
    idempotent; this only supplies the one log line that says how much there was
    to do, which is the difference between "the upgrade did nothing because
    there was nothing to do" and "the upgrade did nothing because it never ran".
    """
    cr.execute("""
        SELECT count(*) FROM project_project_stage
         WHERE active
           AND NOT COALESCE(pl_for_implementation, FALSE)
           AND NOT COALESCE(pl_for_general, FALSE)
           AND NOT COALESCE(pl_for_amc, FALSE)
    """)
    stages = cr.fetchone()[0]
    # `s.active` matters: stages deliberately left archived with projects still
    # on them (the retired "To Do", holding two archived internal projects) are
    # not debris to be cleaned up, and counting them would make the guard report
    # work to do on every upgrade forever.
    cr.execute("""
        SELECT count(*)
          FROM project_project p
          JOIN project_project_stage s ON s.id = p.stage_id
         WHERE s.active
           AND NOT COALESCE(s.pl_for_implementation, FALSE)
           AND NOT COALESCE(s.pl_for_general, FALSE)
           AND NOT COALESCE(s.pl_for_amc, FALSE)
    """)
    projects = cr.fetchone()[0]
    return stages, projects


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
    """Active projects sitting on a stage their own Project Type may not use.

    ARCHIVED projects are deliberately excluded. The constraint this repairs
    fires on write, and nobody writes to an archived project — so the only thing
    "repairing" one achieves is to destroy the record of where it was parked
    when it was archived. Two archived internal projects sit on the retired
    "To Do" stage for exactly this reason: the stage is kept, archived, with
    them on it, and the reconciler used to drag them onto DISC every upgrade.

    If such a project is ever unarchived the constraint will raise on its next
    save, which is the right moment for a person to decide where it belongs —
    far better than a migration having guessed months earlier.
    """
    allows, params = _stage_allows_type_sql('p.ft_project_type')
    cr.execute(
        """
        SELECT p.id
          FROM project_project p
          JOIN project_project_stage s ON s.id = p.stage_id
         WHERE p.active
           AND p.ft_project_type IS NOT NULL
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
    # Stages first, so any ORM write that follows cannot trip
    # _check_stage_for_type.
    #
    # Adoption, not migration. An earlier design created the lifecycle stages
    # fresh, moved every project onto them and converted the HOLD stage into the
    # pl_on_hold flag. Both are gone: the stages are adopted in place, so
    # projects keep the stage they are on, and HOLD is a Kanban stage again.
    adopt_legacy_stages(env)
    backfill_start_dates(env)
    # Last word on the type/stage pairing — catches anything knocked out of step
    # by a classification re-run elsewhere.
    repair_type_stage_mismatches(env)


# ---------------------------------------------------------------------------
# Stage adoption (replaces the old create-new-stages-and-move-projects path)
# ---------------------------------------------------------------------------
# The first design created the lifecycle stages as new records and moved every
# project onto them. It worked, but it rewrote the stage of 76 projects that had
# not actually changed phase — an AMC contract in "Closed" became "Completed", a
# General project in "Discovery" became "Started" — and the audit trail for
# "when did this project reach DEV" became "when did the migration run".
#
# The requirement is the other way round: the new names are ABBREVIATIONS of the
# stages that already exist. Discovery IS DISC. Development IS DEV. So instead
# of creating a second record and moving projects between them, this adopts the
# existing record: it re-points the module's xmlid at the old stage, renames it,
# gives it the type flags and the pipeline sequence, and deletes the duplicate
# the data file created. The projects never move because their stage_id never
# changes — only the row's name does.
#
# Re-pointing the xmlid rather than deleting it is what keeps the rest of the
# module working: _pl_stamp_lifecycle_dates and the allowed-stage lookups all
# resolve stages through env.ref('ft_project_lifecycle.stage_*').
#
# (old stage name, xmlid, new name, sequence, minimum type flags)
_ADOPTIONS = (
    ('discovery',       'stage_disc',    'DISC',    10, ('implementation',)),
    ('development',     'stage_dev',     'DEV',     20, ('implementation',)),
    ('sandbox review',  'stage_srv',     'SRV',     40, ('implementation',)),
    ('user acceptance', 'stage_uat',     'UAT',     50, ('implementation',)),
    ('data upload',     'stage_data',    'DATA',    60, ('implementation',)),
    ('training',        'stage_tra',     'TRA',     70, ('implementation',)),
    ('support',         'stage_support', 'SUPPORT', 80, ('implementation',)),
    # No HOLD. It is retired below, in _RETIRED_STAGES: being parked is the
    # pl_on_hold checkbox on the project form, not a stage.
    ('closed',          'stage_closed',  'CLOSED', 110,
     ('implementation', 'amc', 'general')),
)

# Stages kept exactly as they are, name included, but given a sequence so they
# sit in the right place in the pipeline and a flag so the projects on them stay
# saveable. Production Testing sits where REG would put it and Deployment after
# DATA, which is the phase each of them actually represents.
#
# The flags are stated here rather than inferred from the projects standing on
# them, for the reason set out on _apply_stage_flags. Both are Implementation
# phases: testing a build and deploying it are steps in a delivery, and neither
# has a place in the AMC/General Started -> Working -> Completed flow.
#
# (old stage name, sequence, type flags)
_KEPT_STAGES = (
    ('production testing', 35, ('implementation',)),
    ('deployment', 65, ('implementation',)),
)

# Stages retired outright: archived, flags cleared, xmlid dropped.
#
# "AMC" was briefly adopted as a Kanban column because the requirement listed it
# among the stages. It has no role: AMC is a PROJECT TYPE, and AMC projects run
# Started -> Working (AMC/General) -> Completed like General ones. Nothing routes
# to a stage named AMC, so it only ever drew a permanently empty column that
# invited someone to drag a project onto a dead end. The type is where AMC is
# expressed; filtering or grouping by Project Type is how you see those projects.
#
# Archived rather than deleted, in the manner of every other stage here: seven
# tables carry a foreign key to project.project.stage.
# "HOLD" is retired for a different reason: it is not that nothing routes to it,
# but that pl_on_hold already says the same thing better. A stage can hold only
# one answer, so parking a project overwrote the stage it was parked FROM — the
# one fact needed to resume it — and left the form showing an On Hold checkbox
# and a HOLD stage that could disagree with each other. The checkbox sits
# alongside stage_id, so a project is "in DEV and parked" and comes back to DEV
# on its own. unpark_hold_projects moves whatever is standing on the stage
# before this archives it.
_RETIRED_STAGES = (
    ('amc', 'stage_amc'),
    ('hold', 'stage_hold'),
)

# Old stages merged into an adopted one: their projects move (the only projects
# that do), then the emptied stage is archived.
_MERGES = (
    ('sandbox testing', 'stage_srv'),
)

# The shared AMC/General "Working" stage, relabelled so the Kanban column says
# which two types share it.
_WORKING_LABEL = 'Working (AMC/General)'


def _stage_by_name(cr, name):
    """id of the stage whose en_US name matches (case/space-insensitively)."""
    cr.execute(
        "SELECT id FROM project_project_stage "
        " WHERE lower(trim(name->>'en_US')) = %s ORDER BY id LIMIT 1",
        (name,))
    row = cr.fetchone()
    return row[0] if row else None


def _apply_stage_flags(cr, stage_id, base_flags):
    """Set pl_for_* to the workflow the stage belongs to, and nothing else.

    This used to add in every Project Type found STANDING on the stage, so that
    a project of the wrong type could not become unsaveable — _check_stage_for_type
    rejects a stage its type has no flag for, and the user saw "Stage 'DEV' is
    not part of the General workflow" with no way forward.

    The protection was real; its scope was wrong. A flag is a property of the
    STAGE and applies to every project of that type, so two archived internal
    projects left standing in Development were enough to put DISC and DEV in the
    status bar of all 26 General projects — the whole Implementation pipeline
    offered to projects that run Started -> Working -> Completed. The exception
    was per-project but the mechanism was per-stage.

    So the protection moved to where the exception is: _compute_pl_allowed_stage_ids
    adds a project's OWN current stage to its allowed list. The archived project
    in DEV can still be saved, because DEV is allowed to it in particular, while
    every other General project sees only the General workflow.
    """
    flags = set(base_flags)
    cr.execute(
        "UPDATE project_project_stage "
        "   SET pl_for_implementation = %s, pl_for_amc = %s, pl_for_general = %s "
        " WHERE id = %s",
        ('implementation' in flags, 'amc' in flags, 'general' in flags, stage_id))
    return flags


def _pre_hold_stage_ids(cr, hold_id, project_ids):
    """{project_id: (stage id it was parked FROM, the date it was parked)}.

    Read out of the chatter, because a stage holds one value and moving a
    project onto HOLD overwrote the stage it came from — which is the loss this
    retirement is undoing.

    Matched on the tracking row's INTEGER columns, not the char ones the earlier
    version used. Adoption renames the stage records in place, so the name
    stored in a tracking row is whatever the stage was called on the day it was
    written ("Development" before the upgrade, "DEV" after) while the id is the
    same row throughout.

    DISTINCT ON with a descending date takes the most recent parking: a project
    can have been parked, resumed and parked again.
    """
    if not project_ids:
        return {}
    cr.execute(
        """
        SELECT DISTINCT ON (m.res_id) m.res_id, t.old_value_integer, m.date::date
          FROM mail_tracking_value t
          JOIN mail_message m ON m.id = t.mail_message_id
          JOIN ir_model_fields f ON f.id = t.field_id
         WHERE m.model = 'project.project'
           AND f.model = 'project.project'
           AND f.name = 'stage_id'
           AND m.res_id IN %s
           AND t.new_value_integer = %s
           AND t.old_value_integer IS NOT NULL
         ORDER BY m.res_id, m.date DESC
        """,
        (tuple(project_ids), hold_id))
    return {r[0]: (r[1], r[2]) for r in cr.fetchall()}


def unpark_hold_projects(cr, hold_id):
    """Move everything off the HOLD stage and tick pl_on_hold instead.

    Runs before the stage is archived, because _RETIRED_STAGES deliberately
    refuses to archive a stage somebody is still standing on — archiving it
    under them would leave projects on a stage no workflow offers, unable to be
    saved from the form and invisible on the Kanban.

    Each parked project needs somewhere to land, best-effort in this order:

    1. The stage the chatter says it was parked FROM, if that stage is still
       part of its Project Type's workflow. This is the answer that keeps the
       project's real position in the flow.
    2. Its Project Type's first stage. This loses where the project had got to,
       so every project that falls back to it is named in the log for somebody
       to correct.

    Raw SQL, like the rest of this module's stage work: the ORM would trip
    _check_stage_for_type mid-move (HOLD is being taken out of every workflow,
    which is the state being repaired) and would post a chatter message and a
    tracking row on every project besides.

    Idempotent — once the stage is empty there is nothing to find.
    """
    cr.execute(
        "SELECT id, ft_project_type, name->>'en_US' "
        "  FROM project_project WHERE stage_id = %s ORDER BY id", (hold_id,))
    parked = cr.fetchall()
    if not parked:
        return 0

    # The workflow stages each type may land on, in pipeline order, HOLD itself
    # excluded so it cannot be offered back to the projects leaving it.
    landing = {}
    for ptype, flag in TYPE_STAGE_FLAG.items():
        cr.execute(
            "SELECT id FROM project_project_stage "
            " WHERE active AND %s AND id <> %%s ORDER BY sequence, id" % flag,
            (hold_id,))
        landing[ptype] = [r[0] for r in cr.fetchall()]

    pre_hold = _pre_hold_stage_ids(cr, hold_id, [p[0] for p in parked])
    tracked, fallback, stranded = [], [], []

    for project_id, ptype, name in parked:
        allowed = landing.get(ptype) or []
        if not allowed:
            # No workflow to land in at all: an untyped project, or a type whose
            # stages are all archived. Left where it is, which keeps it saveable
            # (its own stage is always allowed to it) and keeps HOLD active.
            stranded.append((project_id, name))
            continue
        previous, parked_on = pre_hold.get(project_id, (None, None))
        if previous in allowed:
            target, bucket = previous, tracked
        else:
            target, bucket = allowed[0], fallback
        cr.execute(
            "UPDATE project_project "
            "   SET stage_id = %s, pl_on_hold = true, "
            "       pl_hold_date = COALESCE(pl_hold_date, %s, CURRENT_DATE) "
            " WHERE id = %s", (target, parked_on, project_id))
        bucket.append((project_id, name))

    if tracked:
        _logger.info(
            "ft_project_lifecycle: %s project(s) came off the HOLD stage onto "
            "the stage the chatter says they were parked from, now flagged On "
            "Hold: %s", len(tracked),
            ', '.join("%s '%s'" % p for p in tracked))
    if fallback:
        _logger.warning(
            "ft_project_lifecycle: %s project(s) were parked before the stage "
            "change was tracked, so where they had got to is not recorded. "
            "They are flagged On Hold on their Project Type's FIRST stage and "
            "need their real stage set by hand: %s", len(fallback),
            ', '.join("%s '%s'" % p for p in fallback))
    if stranded:
        _logger.error(
            "ft_project_lifecycle: %s project(s) on HOLD have no workflow to "
            "return to (no Project Type, or none of its stages are active). "
            "They are left on HOLD and the stage stays active for them: %s",
            len(stranded), ', '.join("%s '%s'" % p for p in stranded))
    return len(tracked) + len(fallback)


def _retire_duplicate(cr, stage_id):
    """Drop the data file's stage once its xmlid has been moved to the old one.

    Deleted rather than archived when nothing references it, so the Kanban is
    not left with an invisible second "DISC". Falls back to archiving inside a
    savepoint if any foreign key still holds it — seven tables point at
    project.project.stage and losing that history is not worth a tidier list.
    """
    cr.execute("SELECT count(*) FROM project_project WHERE stage_id = %s", (stage_id,))
    if cr.fetchone()[0]:
        return False
    cr.execute("SAVEPOINT drop_dup")
    try:
        cr.execute("DELETE FROM project_project_stage WHERE id = %s", (stage_id,))
        cr.execute("RELEASE SAVEPOINT drop_dup")
        return True
    except Exception:
        cr.execute("ROLLBACK TO SAVEPOINT drop_dup")
        cr.execute(
            "UPDATE project_project_stage SET active = false, "
            "       pl_for_implementation = false, pl_for_amc = false, "
            "       pl_for_general = false "
            " WHERE id = %s", (stage_id,))
        return False


def adopt_legacy_stages(env):
    """Rename the existing stages into the lifecycle instead of moving projects.

    The design this replaced created the lifecycle stages as new records and
    moved all 299 projects onto them; this one adopts the records that are
    already there, so a project's stage_id is untouched and its position in the
    flow is exactly what it was yesterday.

    Only two kinds of project move, and both were agreed explicitly:

    * the ones on a stage being MERGED into another (Sandbox Testing into SRV) —
      two rows cannot become one row without the projects on one of them moving;
    * ACTIVE non-Implementation projects sitting on an Implementation-only
      stage. They go to the shared Working stage. Archived ones stay where they
      are and their stage keeps a flag for them, because moving a project nobody
      can see serves nothing and loses where it was.

    Idempotent: adoption is skipped for any stage whose xmlid already points at a
    record carrying the target name, so a second run finds nothing to do.
    """
    snapshotted = _snapshot_stages(env)
    cr = env.cr

    def xmlid_target(xmlid):
        cr.execute(
            "SELECT res_id FROM ir_model_data "
            " WHERE module='ft_project_lifecycle' AND model='project.project.stage' "
            "   AND name=%s", (xmlid,))
        row = cr.fetchone()
        return row[0] if row else None

    adopted, renamed_only, moved = 0, 0, 0

    # --- 1. Adopt: point the xmlid at the old record, rename it, place it. ----
    for old_name, xmlid, new_name, sequence, _flags in _ADOPTIONS:
        current_id = xmlid_target(xmlid)
        old_id = _stage_by_name(cr, old_name)
        if current_id is None:
            _logger.warning(
                "ft_project_lifecycle: xmlid %s missing; skipping adoption of "
                "'%s'.", xmlid, old_name)
            continue
        if old_id is None or old_id == current_id:
            # No legacy counterpart (a fresh database), or already adopted.
            cr.execute(
                "UPDATE project_project_stage SET name = jsonb_build_object('en_US', %s::text), sequence = %s, "
                "       active = true WHERE id = %s",
                (new_name, sequence, current_id))
            renamed_only += 1
            continue
        cr.execute(
            "UPDATE ir_model_data SET res_id = %s "
            " WHERE module='ft_project_lifecycle' AND model='project.project.stage' "
            "   AND name = %s", (old_id, xmlid))
        cr.execute(
            "UPDATE project_project_stage SET name = jsonb_build_object('en_US', %s::text), sequence = %s, "
            "       active = true WHERE id = %s",
            (new_name, sequence, old_id))
        _retire_duplicate(cr, current_id)
        adopted += 1
        _logger.info(
            "ft_project_lifecycle: adopted stage '%s' (id %s) as %s; the "
            "projects on it did not move.", old_name, old_id, new_name)

    # --- 2. Merge: the only projects that change stage by stage identity. ----
    for old_name, into_xmlid in _MERGES:
        old_id = _stage_by_name(cr, old_name)
        target_id = xmlid_target(into_xmlid)
        if not old_id or not target_id or old_id == target_id:
            continue
        cr.execute(
            "UPDATE project_project SET stage_id = %s WHERE stage_id = %s",
            (target_id, old_id))
        merged = cr.rowcount
        moved += merged
        cr.execute(
            "UPDATE project_project_stage SET active = false, "
            "       pl_for_implementation = false, pl_for_amc = false, "
            "       pl_for_general = false WHERE id = %s", (old_id,))
        _logger.info(
            "ft_project_lifecycle: merged '%s' into %s (%s project(s) moved); "
            "the emptied stage is archived, not deleted.",
            old_name, into_xmlid, merged)

    # --- 3. Active non-Implementation projects off Implementation-only stages.
    working_id = xmlid_target('stage_working')
    impl_only = [
        xmlid_target(x) for _o, x, _n, _s, flags in _ADOPTIONS
        if tuple(flags) == ('implementation',)
    ]
    impl_only = [i for i in impl_only if i]
    if working_id and impl_only:
        cr.execute(
            "SELECT id, name->>'en_US', ft_project_type FROM project_project "
            " WHERE stage_id IN %s AND active "
            "   AND ft_project_type IS NOT NULL "
            "   AND ft_project_type <> 'implementation'",
            (tuple(impl_only),))
        strays = cr.fetchall()
        if strays:
            cr.execute(
                "UPDATE project_project SET stage_id = %s WHERE id IN %s",
                (working_id, tuple(s[0] for s in strays)))
            moved += len(strays)
            _logger.info(
                "ft_project_lifecycle: moved %s active non-Implementation "
                "project(s) onto %s: %s", len(strays), _WORKING_LABEL,
                ', '.join("%s '%s' (%s)" % s for s in strays))

    # --- 4. The AMC/General flow, relabelled so the shared column says so. ----
    for xmlid, label, sequence in (
            ('stage_started', 'Started', 90),
            ('stage_working', _WORKING_LABEL, 95),
            ('stage_completed', 'Completed', 100)):
        sid = xmlid_target(xmlid)
        if sid:
            cr.execute(
                "UPDATE project_project_stage SET name = jsonb_build_object('en_US', %s::text), sequence = %s, "
                "       active = true WHERE id = %s",
                (label, sequence, sid))
            _apply_stage_flags(cr, sid, ('amc', 'general'))

    # --- 5. Stages kept exactly as they are, placed and flagged. -------------
    for name, sequence, flags in _KEPT_STAGES:
        sid = _stage_by_name(cr, name)
        if sid:
            cr.execute(
                "UPDATE project_project_stage SET sequence = %s WHERE id = %s",
                (sequence, sid))
            _apply_stage_flags(cr, sid, flags)

    # --- 6. Flags on every adopted stage, last, once all moves are done. -----
    for _old_name, xmlid, _new_name, _sequence, flags in _ADOPTIONS:
        sid = xmlid_target(xmlid)
        if sid:
            _apply_stage_flags(cr, sid, flags)

    # --- 6a. Empty the HOLD stage before 6b tries to archive it. -------------
    # After the flags above, so a landing stage is chosen against the workflow
    # as it finally stands rather than as it stood mid-adoption.
    hold_id = xmlid_target('stage_hold') or _stage_by_name(cr, 'hold')
    if hold_id:
        moved += unpark_hold_projects(cr, hold_id)

    # --- 6b. Retire stages that have no role in any workflow. ----------------
    for name, xmlid in _RETIRED_STAGES:
        sid = xmlid_target(xmlid) or _stage_by_name(cr, name)
        if not sid:
            continue
        cr.execute(
            "SELECT count(*) FROM project_project WHERE stage_id = %s", (sid,))
        held = cr.fetchone()[0]
        if held:
            # Never archive a stage somebody is still on: they would be stranded
            # and unable to save. Loud, and left for a person to move.
            _logger.error(
                "ft_project_lifecycle: stage '%s' still holds %s project(s); "
                "leaving it active rather than stranding them.", name, held)
            continue
        cr.execute(
            "UPDATE project_project_stage "
            "   SET active = false, pl_for_implementation = false, "
            "       pl_for_amc = false, pl_for_general = false "
            " WHERE id = %s", (sid,))
        # Drop the xmlid too, so ir.model.data's end-of-update sweep does not
        # see an orphan and try to DELETE the stage row we just archived.
        cr.execute(
            "DELETE FROM ir_model_data "
            " WHERE module='ft_project_lifecycle' "
            "   AND model='project.project.stage' AND name = %s", (xmlid,))
        _logger.info(
            "ft_project_lifecycle: retired the '%s' stage — it held nothing and "
            "no workflow routes to it; AMC is a Project Type, not a stage.",
            name)

    # --- 7. Archive legacy stages left holding nothing. ----------------------
    cr.execute("""
        UPDATE project_project_stage s SET active = false
         WHERE s.active
           AND NOT COALESCE(s.pl_for_implementation, FALSE)
           AND NOT COALESCE(s.pl_for_general, FALSE)
           AND NOT COALESCE(s.pl_for_amc, FALSE)
           AND NOT EXISTS (SELECT 1 FROM project_project p WHERE p.stage_id = s.id)
    """)
    emptied = cr.rowcount

    cr.execute("""
        UPDATE %s b SET new_stage_id = p.stage_id
          FROM project_project p WHERE p.id = b.project_id
    """ % _BACKUP_TABLE)

    env.invalidate_all()
    _logger.info(
        "ft_project_lifecycle: stage adoption done — snapshotted %s, adopted "
        "%s stage(s), renamed %s in place, archived %s empty legacy stage(s), "
        "and moved %s project(s) in total.",
        snapshotted, adopted, renamed_only, emptied, moved)
    return moved
