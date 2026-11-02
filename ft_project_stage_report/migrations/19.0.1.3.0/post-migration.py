# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Rebuild every stored stage line after the planned-date re-pairing.

19.0.1.3.0 pairs each stage with the date the project must REACH it by
(project_date_extension 19.0.1.7.0's STAGE_PLANNED_DATE_FIELD) and computes
Overdue Days from the stage's entry date. The lines are stored rows that only
the write triggers and the nightly cron refresh, so without this step every
project kept its old planned dates and overdue figures until the next night -
or forever, for projects nobody touches any more. Same rebuild as the install
hook; cheap enough to run inline (a few thousand rows).
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    lines = env["ft.project.stage.line"]._rebuild_for_projects()
    _logger.info(
        "ft_project_stage_report 19.0.1.3.0: rebuilt %s stage line(s) with the "
        "reach-by planned dates.", len(lines))
