"""Let this release's rewritten project purposes replace the seeded ones.

The purpose records ship with ``noupdate="1"`` so that prompts an admin has
edited are never clobbered by an upgrade. That protection also blocks the
rewrite shipped in 18.0.1.1.0:

* milestones re-aimed from (unanalysable) delivery timing to billing, and made
  opt-in via ``include_milestones``;
* explicit section ordering, so reports stop coming back rearranged;
* explicit "pending is not late" guards.

So we clear noupdate for these specific xmlids, let the data file refresh them
during this upgrade, and restore the flag in post-migration.

Only ``purpose_project_*`` is touched — sales purposes are left alone.
"""


def migrate(cr, version):
    if not version:
        # Fresh install: the data file creates the records correctly anyway.
        return
    cr.execute(
        """
        UPDATE ir_model_data
           SET noupdate = false
         WHERE module = 'ft_ai_sales_insights'
           AND model = 'ft.ai.insights.purpose'
           AND name LIKE 'purpose_project_%%'
        """
    )
