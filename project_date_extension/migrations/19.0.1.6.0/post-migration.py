# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Back-fill "Stage to be Extended" on existing Date Extension Requests.

Requests raised before 19.0.1.6.0 only carry the lifecycle date they move
(date_to_extend_id). The stage whose planned end that date is (see
STAGE_PLANNED_DATE_FIELD) is filled in so the stage-wise reports and the
list's new column cover history too. Dates that mark no stage's end (Start,
Support Start) are left without a stage. The new stored computed columns
(extension_days / is_preponement / delay_days) are computed by the ORM when
the columns are added; nothing to do for them here.

NOTE: "planned end" above is the pairing as it stood in 1.6.0 (a stage
with the NEXT stage's date). 19.0.1.7.0 re-pairs every stage with its OWN
date and its migration re-derives the stage on every request, so what
this script back-filled is corrected there.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    from odoo.addons.project_date_extension.models.project_date_extension_request import (
        STAGE_PLANNED_DATE_FIELD,
        _stage_key,
    )
    stages = env["project.project.stage"].with_context(active_test=False).search([])
    stage_by_field = {}
    for stage in stages:
        fname = STAGE_PLANNED_DATE_FIELD.get(_stage_key(stage))
        if fname:
            stage_by_field.setdefault(fname, stage)
    requests = env["project.date.extension.request"].search(
        [("stage_to_extend_id", "=", False), ("date_to_extend_id", "!=", False)]
    )
    for req in requests:
        stage = stage_by_field.get(req.date_to_extend_id.field_name)
        if stage:
            # Plain column update: the stage is derived from the date, so
            # the date must not be recomputed (it would be the same anyway)
            # and no tracking message is wanted on old records.
            cr.execute(
                "UPDATE project_date_extension_request SET stage_to_extend_id = %s WHERE id = %s",
                (stage.id, req.id),
            )
