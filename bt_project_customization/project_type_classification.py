"""Classify projects that carry no ``ft_project_type`` yet.

Shared by two migrations, which is the whole reason it is a module rather than
inline SQL:

* ``migrations/19.0.1.3.0`` runs it when the field is first introduced, where
  every row is untyped because the column has only just been added;
* ``migrations/19.0.1.11.0`` runs it again on databases that took the 19.0.1.3.0
  upgrade while it was broken (see below) and came out of it with rows still
  NULL.

Both need the identical rules. Two copies of them would drift, and the second
copy would be written months after anybody remembered why 'general' is applied
before 'amc'.

WHY THE FIRST VERSION UNDER-CLASSIFIED
--------------------------------------
The original 19.0.1.3.0 script was written when ``ft_project_type`` still
carried ``default='implementation'``, so by the time it ran the ORM had already
stamped every row and nothing was NULL. Its two name-based passes were written
against that assumption::

    WHERE p.ft_project_type != 'general'   -- "not already classified general"

The default was later removed on purpose (see the field comment in
``models/project_project.py``: a wrong classification inherited silently was
worse than a form that refuses to save until somebody picks). From then on the
column arrived full of NULLs, and ``NULL != 'general'`` is NULL, not TRUE — so
both name passes silently matched **zero** rows on every database upgraded
after that change. Only the two stage-based passes, which carry no such
predicate, did anything.

Measured on the 2026-08-18 production copy, restored and upgraded: the script
reported the split it was written to produce as 219/54/26, and produced
0 implementation / 35 amc / 16 general with 248 rows left NULL. The 19 AMC
contracts and 10 internal projects that only the name rules can recognise were
all in that residue, and so was every implementation project, because
'implementation' was never assigned by anything but the vanished default.

WHAT CHANGED HERE
-----------------
1. ``!=`` became ``IS DISTINCT FROM`` so the name passes see NULL rows.
2. A final pass assigns the residue to 'implementation' explicitly, taking over
   the job the default used to do.
3. Every pass is confined to the set of rows that were NULL when the function
   was entered, captured once up front. On a first run that is every row, so the
   behaviour is exactly what 19.0.1.3.0 was always meant to have. On a re-run
   against a half-classified database it is what makes the function safe: a
   project somebody has since classified by hand cannot be overwritten by a
   guess from a name regex.
"""

import logging

_logger = logging.getLogger(__name__)

# Names that mark internal, non-delivery work. Anchored where the fragment is
# short enough to appear inside a client name ('^test ', '^abc$'), loose where
# it is not ('fingertip', 'standup'). Verified against all 299 projects: 20
# matches, every one of them genuinely internal, no client project caught.
INTERNAL_NAME_RE = r'(fingertip|^ftp |internal|bench|^test |test purpose|standup|^abc$)'

# '\yamc' is a word boundary before AMC only, NOT '\yamc\y' on both sides.
# A trailing boundary would drop "ORONO-AMC2024", where the year runs straight
# into the acronym. A leading one is what keeps an innocent "Ramco" or "Camco"
# out of the AMC bucket, which a plain LIKE '%amc%' would happily sweep in.
AMC_NAME_RE = r'\yamc'

# The residue. Everything the stage and name rules cannot speak for is client
# delivery work — see the accuracy note in migrations/19.0.1.3.0.
RESIDUE_TYPE = 'implementation'


def classify_untyped_projects(cr):
    """Fill ``ft_project_type`` on every project that has none.

    Returns a dict of counts for logging. Touches only rows that are NULL on
    entry, so it is safe to call on a database that is already partly or wholly
    classified — on a healthy one it selects nothing and returns zeros.
    """
    # The working set, fixed before the first UPDATE. Every pass below is
    # scoped to it, which is what stops a second run from re-deciding a type
    # somebody has since corrected by hand.
    cr.execute("SELECT id FROM project_project WHERE ft_project_type IS NULL")
    untyped = tuple(r[0] for r in cr.fetchall())
    if not untyped:
        _logger.info(
            "bt_project_customization: every project already carries a "
            "Project Type; nothing to classify.")
        return {'untyped': 0}

    # Stage names are a translated jsonb column, so they are read at the
    # 'en_US' key rather than matched with a plain equality on `name`, for the
    # same reason _ft_source_boundaries forces lang='en_US' in the model: a
    # database whose stages have been translated would otherwise match nothing.
    #
    # Order matters, and it is the original order. General is applied first and
    # AMC second so that a project carrying both signals resolves to AMC — the
    # contract is the fact worth keeping. Within `untyped` the later passes are
    # deliberately free to overwrite what the earlier ones set, which is how
    # that precedence is expressed.
    #
    # Archived projects are included: 7 of the 8 are internal work, and leaving
    # them untyped would both misreport them under the Archived filter and
    # leave them stranded when ft_project_lifecycle moves projects onto the new
    # stages, which keys its mapping off the type.
    cr.execute(
        """
        UPDATE project_project p
           SET ft_project_type = 'general'
          FROM project_project_stage s
         WHERE p.stage_id = s.id
           AND p.id IN %s
           AND lower(trim(s.name->>'en_US')) = 'general'
        """,
        (untyped,),
    )
    by_stage_general = cr.rowcount

    cr.execute(
        """
        UPDATE project_project p
           SET ft_project_type = 'general'
         WHERE p.id IN %s
           AND p.ft_project_type IS DISTINCT FROM 'general'
           AND p.name->>'en_US' ~* %s
        """,
        (untyped, INTERNAL_NAME_RE),
    )
    by_name_general = cr.rowcount

    cr.execute(
        """
        UPDATE project_project p
           SET ft_project_type = 'amc'
          FROM project_project_stage s
         WHERE p.stage_id = s.id
           AND p.id IN %s
           AND lower(trim(s.name->>'en_US')) = 'amc'
        """,
        (untyped,),
    )
    by_stage_amc = cr.rowcount

    cr.execute(
        """
        UPDATE project_project p
           SET ft_project_type = 'amc'
         WHERE p.id IN %s
           AND p.ft_project_type IS DISTINCT FROM 'amc'
           AND p.name->>'en_US' ~* %s
        """,
        (untyped, AMC_NAME_RE),
    )
    by_name_amc = cr.rowcount

    # The residue, and the pass that replaces the field default. Without it the
    # rows the rules cannot speak for stay NULL, and a NULL type is not a
    # cosmetic gap: ft_project_type is required, so the project cannot be saved
    # from the form, and ft_project_lifecycle's _STAGE_MAP is keyed by type, so
    # the project can never be moved off the old pipeline either.
    cr.execute(
        """
        UPDATE project_project
           SET ft_project_type = %s
         WHERE id IN %s
           AND ft_project_type IS NULL
        """,
        (RESIDUE_TYPE, untyped),
    )
    residue = cr.rowcount

    cr.execute(
        "SELECT ft_project_type, count(*) FROM project_project GROUP BY 1")
    totals = dict(cr.fetchall())

    counts = {
        'untyped': len(untyped),
        'by_stage_general': by_stage_general,
        'by_name_general': by_name_general,
        'by_stage_amc': by_stage_amc,
        'by_name_amc': by_name_amc,
        'residue': residue,
    }
    _logger.info(
        "bt_project_customization: classified %s untyped project(s) — "
        "general %s (%s by stage, %s by name), amc %s (%s by stage, %s by "
        "name), %s residue to %s; database split now implementation=%s "
        "amc=%s general=%s",
        len(untyped),
        by_stage_general + by_name_general, by_stage_general, by_name_general,
        by_stage_amc + by_name_amc, by_stage_amc, by_name_amc,
        residue, RESIDUE_TYPE,
        totals.get('implementation', 0),
        totals.get('amc', 0),
        totals.get('general', 0),
    )

    # Nothing may be left NULL: the whole point of the residue pass. Loud rather
    # than silent, because the rows it would leave behind are unsaveable.
    cr.execute("SELECT count(*) FROM project_project WHERE ft_project_type IS NULL")
    still_null = cr.fetchone()[0]
    if still_null:
        _logger.error(
            "bt_project_customization: %s project(s) still have no Project "
            "Type after classification. They cannot be saved from the form "
            "until this is corrected.", still_null)

    return counts
