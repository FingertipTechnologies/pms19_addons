# -*- coding: utf-8 -*-
"""Give every existing Implementation project the Milestone Templates it
does not have yet (0%, no due date). Milestones already on the project are
kept as they are."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    projects = env['project.project'].with_context(active_test=False).search([
        ('ft_project_type', '=', 'implementation'), ('is_template', '=', False)])
    added = projects._ft_add_missing_template_milestones()
    _logger.info("ft_implementation_milestone 19.0.1.4.0: %s template milestone(s) "
                 "added on %s Implementation project(s).", added, len(projects))
