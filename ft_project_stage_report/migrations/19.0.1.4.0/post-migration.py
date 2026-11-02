# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Rebuild every stored stage line with the new Overdue Days rule.

19.0.1.4.0 counts the approved Date Extension days of a stage as its delay:
Overdue Days = Extension Days + the days still missed after the extension.
The lines are stored rows that only the write triggers and the nightly cron
refresh, so without this step every extended project kept its old overdue
figures until the next night - or forever, for projects nobody touches any
more. Same rebuild as the install hook; cheap enough to run inline.
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
        "ft_project_stage_report 19.0.1.4.0: rebuilt %s stage line(s) with "
        "extension days counted as overdue.", len(lines))
