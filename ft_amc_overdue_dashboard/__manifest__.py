{
    'name': 'FT AMC Task Overdue Dashboard',
    # 19.0.1.1.0: overdue is measured from the ORIGINAL deadline
    #   (pwf_original_deadline), completed tasks carry a frozen
    #   ft_historical_overdue_days stamped at completion, cancelled tasks are
    #   never listed, the original deadline is locked against RPC changes,
    #   and a post_init_hook backfills both fields on existing tasks.
    # 19.0.1.2.0: no page of its own any more. The standalone client action
    #   and its PMS > AMC Reports menu are gone; the table is embedded in the
    #   Project Dashboard (ft_project_dashboard) below Implementation Stages,
    #   scoped by that board's Project / Project Manager pickers (new
    #   manager_id filter), with the KPI tiles folded into a summary line.
    # 19.0.1.3.0: the original-deadline / historical-overdue backfill runs on
    #   every upgrade (migrations/19.0.1.3.0), not only on install: a database
    #   where the install hook did not take showed the current deadline under
    #   "Original Deadline" for every task (the fallback) and could not repair
    #   itself without a shell.
    # 19.0.1.4.0: a task in Status "Deployed" (state 1_deployed, added by
    #   ft_amc_payment_milestone after Done) counts as completed: listed with
    #   "Include completed", backfilled by the hook, and it keeps the figure
    #   frozen when it became Done (re-stamped only when date_end is re-dated).
    #   No migration.
    'version': '19.0.1.4.0',
    'category': 'Project',
    'license': 'LGPL-3',
    'author': 'Fingertip',
    'website': '',
    'summary': 'AMC Task Overdue table (task age and days overdue) inside '
               'the Project Dashboard',
    'description': """
FT AMC Task Overdue Dashboard
=============================
An OWL table embedded in the Project Dashboard (ft_project_dashboard,
Dashboards > Project, below Implementation Stages and above Resource Status)
listing the tasks of every AMC project:

 * Project Name, Task Name, Stage, Original Deadline, Current Deadline;
 * Total Days - the task's age in whole calendar days since it was created
   (stopped at completion for a completed task);
 * Overdue Days - calendar days the task is past its ORIGINAL deadline, not
   the latest revised one. For a completed task it is the figure frozen on
   the day of completion (project.task.ft_historical_overdue_days), so it
   never changes afterwards.

The dashboard's header Project and Project Manager pickers scope the table
like every other section of that board. Its own tools are a search over
project / task name, "Overdue only" (with the overdue count on the toggle)
and "Include completed" (completed tasks with their frozen figure; cancelled
tasks are never listed), plus a one-line summary of the counts: tasks,
overdue tasks, summed overdue days.

The original deadline (pwf_original_deadline, ft_pms_planning_workflow) is
locked once set: a non-superuser write that would change it is refused. The
install hook backfills it from the chatter's deadline tracking for tasks that
predate the tracking, and stamps the frozen figure on tasks already completed.

Day arithmetic follows ft_task_hours_tracker: local calendar days in the
reader's timezone, never UTC days.

Where: Dashboards > Project (Project Dashboard, administrators), the
"AMC Task Overdue" table. There is no separate menu.
""",
    'depends': [
        'project',
        'bt_project_customization',
        'ft_task_hours_tracker',
        'ft_pms_planning_workflow',
        'ft_amc_monthly_timesheet',
        'ft_project_dashboard',
    ],
    'data': [
        'security/ir.model.access.csv',
    ],
    # The js extends ProjectDashboard.components and the xml extends its
    # template (t-inherit), so both must load after ft_project_dashboard's
    # assets; the module dependency guarantees that order.
    'assets': {
        'web.assets_backend': [
            'ft_amc_overdue_dashboard/static/src/scss/amc_overdue_dashboard.scss',
            'ft_amc_overdue_dashboard/static/src/js/amc_overdue_dashboard.js',
            'ft_amc_overdue_dashboard/static/src/xml/amc_overdue_dashboard.xml',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
}
