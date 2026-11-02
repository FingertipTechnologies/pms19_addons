# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Rebuild every stored stage line: Overdue Days is now the approved Date
Extension days of the stage only (the planned-date arithmetic is gone)."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    lines = env["ft.project.stage.line"]._rebuild_for_projects()
    _logger.info(
        "ft_project_stage_report 19.0.1.5.0: rebuilt %s stage line(s) with "
        "overdue days = approved extension days only.", len(lines))
