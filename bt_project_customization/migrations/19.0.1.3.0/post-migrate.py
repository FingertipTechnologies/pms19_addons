"""Classify every existing project as Implementation, AMC or General.

``ft_project_type`` is required with a default of 'implementation', so by the
time this runs the ORM has already stamped that value on all 299 rows. This
corrects the two types the default cannot know about.

There is nothing to read the type FROM. The obvious candidate, the legacy
``status`` Selection, is NULL on every single project — it was never wired into
a view (its <field> is commented out) and so was never filled. ``partner_id``,
the other candidate, is set on 8 projects out of 299. Both are dead ends.

What does carry the signal is ``stage_id``, precisely because the pipeline
conflated type with lifecycle: AMC and General are stages sitting alongside
Development and Closed. That covers the projects still in flight, but says
nothing about the 172 in Closed or Hold, whose type the stage overwrote when
they finished. For those the project NAME carries it — AMC work is named
"<Client> AMC <year>" without exception on this database, which recovers 19 AMC
contracts that the stage alone would have mislabelled as implementations.

Accuracy, measured against the live data at the time of writing:

  amc             54  (35 by stage, 19 more by name)
  general         26  (16 by the General stage, 10 by name)
  implementation 219  (43 in delivery stages, 6 in Support, the rest closed)

The implementation bucket is the residue and is the one to distrust: roughly
155 of it is Closed projects with no positive evidence either way. Sampling
them they are overwhelmingly completed client delivery (Trifecta Release-1,
Cyrix Health Care Release-1, Nippon Toyota), which is why the residue falls
here rather than in General, but a handful of product and internal projects
that dodged the name rules will be sitting in it and need correcting by hand.

Known miss: "JRCAMC need to remove need to be deleted" lands in implementation
because the word-boundary rule below will not see AMC inside "JRCAMC". It is
junk flagged for deletion, so it is not worth loosening the rule for.

Raw SQL on purpose, in the manner of the earlier migrations in this module:
``ft_project_type`` is tracked, so writing these through the ORM would post a
mail.tracking row and a chatter message on every project in the database, and
would retrigger the stored computes hanging off project.project besides.
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


def migrate(cr, version):
    # Nothing to backfill on a fresh install: the default has already put every
    # (non-existent) row where it belongs.
    if not version:
        return

    # Stage names are a translated jsonb column, so they are read at the
    # 'en_US' key rather than matched with a plain equality on `name`, for the
    # same reason _ft_source_boundaries forces lang='en_US' in the model: a
    # database whose stages have been translated would otherwise match nothing
    # and leave every project on the default.
    #
    # Order matters. General is applied first and AMC second, so that a project
    # carrying both signals resolves to AMC — the contract is the fact worth
    # keeping. Archived projects are included: 7 of the 8 are internal work,
    # and leaving them defaulted would misreport them the moment anyone
    # searches with the Archived filter on.
    cr.execute(
        """
        UPDATE project_project p
           SET ft_project_type = 'general'
          FROM project_project_stage s
         WHERE p.stage_id = s.id
           AND lower(trim(s.name->>'en_US')) = 'general'
        """
    )
    by_stage_general = cr.rowcount

    cr.execute(
        """
        UPDATE project_project p
           SET ft_project_type = 'general'
         WHERE p.ft_project_type != 'general'
           AND p.name->>'en_US' ~* %s
        """,
        (INTERNAL_NAME_RE,),
    )
    by_name_general = cr.rowcount

    cr.execute(
        """
        UPDATE project_project p
           SET ft_project_type = 'amc'
          FROM project_project_stage s
         WHERE p.stage_id = s.id
           AND lower(trim(s.name->>'en_US')) = 'amc'
        """
    )
    by_stage_amc = cr.rowcount

    cr.execute(
        """
        UPDATE project_project p
           SET ft_project_type = 'amc'
         WHERE p.ft_project_type != 'amc'
           AND p.name->>'en_US' ~* %s
        """,
        (AMC_NAME_RE,),
    )
    by_name_amc = cr.rowcount

    cr.execute(
        "SELECT ft_project_type, count(*) FROM project_project GROUP BY 1 ORDER BY 1"
    )
    totals = dict(cr.fetchall())

    _logger.info(
        "bt_project_customization: classified projects by type — "
        "general %s (%s by stage, %s by name), amc %s (%s by stage, %s by name); "
        "final split implementation=%s amc=%s general=%s",
        by_stage_general + by_name_general, by_stage_general, by_name_general,
        by_stage_amc + by_name_amc, by_stage_amc, by_name_amc,
        totals.get('implementation', 0),
        totals.get('amc', 0),
        totals.get('general', 0),
    )
