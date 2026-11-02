# -*- coding: utf-8 -*-
"""Clear AMC approvals left on tasks of non-AMC projects: the approval only
applies to AMC projects, and those stale values made the "Approved" filter
list tasks that show no approval."""


def migrate(cr, version):
    cr.execute("""
        UPDATE project_task t
           SET pwf_amc_approval = NULL,
               pwf_amc_approved_by_id = NULL,
               pwf_amc_approved_on = NULL
          FROM project_project p
         WHERE p.id = t.project_id
           AND t.pwf_amc_approval IS NOT NULL
           AND COALESCE(p.ft_project_type, '') <> 'amc'
    """)
