"""Backfill the Project Types that the 19.0.1.3.0 classification never assigned.

19.0.1.3.0 was written against a field that still carried
``default='implementation'``. Once that default was deliberately removed, the
column arrived full of NULLs, its two name-based passes compared ``!= 'general'``
against NULL and matched nothing, and no pass assigned 'implementation' at all —
the vanished default had been doing that. Every database upgraded through
19.0.1.3.0 after the default was dropped therefore came out of it with the
majority of its projects still untyped. The 2026-08-18 production copy came out
as 0 implementation / 35 amc / 16 general, with 248 rows NULL.

A numbered migration cannot be re-run once a database has passed its version,
so fixing 19.0.1.3.0 in place only helps databases restored from a backup old
enough to still need it. This one exists for the databases already past it.

It is the same function, on the same rules, and it only ever touches rows that
are NULL — so on a database that was classified correctly the first time it
selects nothing and logs one line.

Why the NULLs matter beyond the Kanban being wrong:

* ``ft_project_type`` is required, so a project holding NULL cannot be saved
  from its form. It is a required field only at ORM level — the column is
  nullable — which is exactly why the rows could be written in the first place
  and why nobody noticed until a grouped view put them in an unnamed column.
* ``ft_project_lifecycle`` keys its old-stage-to-new-stage map by Project Type.
  An untyped project matches no arm of that map, so it is left on the old
  pipeline; and because it is left there, the install hook refuses to archive
  the old stages, which is why drained legacy stages such as General and AMC
  stay on the Kanban as permanently empty columns.

The stage half of that is repaired by ft_project_lifecycle, whose ``0.0.0``
post-migrate runs after every other module in the upgrade — including this one.
That ordering is what makes this script's job finish: fill the types here, and
the lifecycle module moves the newly-typed projects onto the right stages and
retires the empty ones immediately afterwards, in the same upgrade.
"""

from odoo.addons.bt_project_customization.project_type_classification import (
    classify_untyped_projects,
)


def migrate(cr, version):
    if not version:
        return

    classify_untyped_projects(cr)
