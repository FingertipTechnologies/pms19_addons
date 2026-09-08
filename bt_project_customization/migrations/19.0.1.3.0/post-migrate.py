"""Classify every existing project as Implementation, AMC or General.

The rules themselves live in ``project_type_classification`` because a later
migration (19.0.1.11.0) has to run the identical ones over the databases this
version left half-done; that module's docstring carries the full account of
what went wrong and what changed. In short: this script was written against a
field that still had ``default='implementation'``, so it assumed no row could
be NULL, and its two name-based passes stopped matching anything the moment the
default was removed.

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
because the word-boundary rule will not see AMC inside "JRCAMC". It is junk
flagged for deletion, so it is not worth loosening the rule for.

Raw SQL on purpose, in the manner of the earlier migrations in this module:
``ft_project_type`` is tracked, so writing these through the ORM would post a
mail.tracking row and a chatter message on every project in the database, and
would retrigger the stored computes hanging off project.project besides.
"""

from odoo.addons.bt_project_customization.project_type_classification import (
    classify_untyped_projects,
)


def migrate(cr, version):
    # Nothing to backfill on a fresh install: there are no rows to classify.
    if not version:
        return

    classify_untyped_projects(cr)
