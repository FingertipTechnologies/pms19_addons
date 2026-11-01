# -*- coding: utf-8 -*-
"""Monthly Customer Feedback is now on by default. Switch it on for every
existing project that is not archived, closed or on hold. Written in SQL: the
project form refused the toggle on projects without a Closed Date, and the
ORM write would run the project's other save checks for no reason."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Project = env["project.project"].with_context(active_test=True)
    domain = [("ft_feedback_monthly_enabled", "=", False)]
    if "is_template" in Project._fields:
        domain.append(("is_template", "=", False))
    projects = Project.search(domain)
    projects = projects.filtered(
        lambda p: _active_project(env, p)
    )
    if projects:
        cr.execute(
            "UPDATE project_project SET ft_feedback_monthly_enabled = true "
            "WHERE id IN %s",
            (tuple(projects.ids),),
        )
        projects.invalidate_recordset(["ft_feedback_monthly_enabled"])


def _active_project(env, project):
    closed_stage = env.ref("ft_project_lifecycle.stage_closed", raise_if_not_found=False)
    if closed_stage and "stage_id" in project._fields and project.stage_id == closed_stage:
        return False
    if "pl_on_hold" in project._fields and project.pl_on_hold:
        return False
    if "status" in project._fields and project.status in ("closed", "hold"):
        return False
    return True
