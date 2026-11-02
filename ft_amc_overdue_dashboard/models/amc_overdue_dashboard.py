from odoo import api, fields, models

# AMC projects are recognised by ft_project_type alone, never by stage: AMC
# and General projects share one stage ('Working (AMC/General)'), so no stage
# test can tell them apart. Imported from ft_project_dashboard rather than
# restated so the two boards can never disagree about what "AMC" means.
from odoo.addons.ft_project_dashboard.models.project_dashboard import (
    AMC_PROJECT_TYPE,
)


class FtAmcOverdueDashboard(models.TransientModel):
    _name = 'ft.amc.overdue.dashboard'
    _description = 'AMC Task Overdue table data provider'

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _amc_project_domain(self):
        """Live AMC projects: the only projects the board ever reports on.

        ``active`` is explicit even though search() already drops archived
        projects, so the scope reads the same here and in the task domain
        below, where the leaf is traversed through ``project_id``.
        """
        return [
            ('active', '=', True),
            ('ft_project_type', '=', AMC_PROJECT_TYPE),
        ]

    def _task_domain(self, filters):
        """Tasks in scope for a set of filters.

        Open = not ``is_closed``, i.e. ``state`` outside CLOSED_STATES (Done /
        Cancelled). bt_project_customization stamps ``state = '1_done'`` on
        every move into a Completed stage, so this agrees with the stage-based
        "delivered" used elsewhere in the PMS while staying a plain, indexed
        column to search on.

        ``include_closed`` adds the COMPLETED tasks only (``state = '1_done'``,
        with their frozen overdue figure). A cancelled task (``1_canceled``)
        was never delivered late or on time, so it is never listed, whatever
        the filters.

        ``project_id`` and ``manager_id`` are the Project Dashboard's two
        header pickers, passed through by the embedded table so it narrows
        with every other section of that board. ``manager_id`` is a res.users
        id — project.project.user_id, the Project Manager on the project
        form — and is a PROJECT-level scope, exactly as ft_project_dashboard
        reads it: it keeps the tasks of the projects that person runs,
        whoever the tasks are assigned to. Both are ignored when falsy ('' /
        None / 0), which is how the dashboard says "all".

        Task templates (Odoo 19 ``is_template``) are never work to chase, and
        are left out for the same reason the auto-complete cron leaves them.
        """
        domain = [
            ('active', '=', True),
            ('is_template', '=', False),
            ('project_id.active', '=', True),
            ('project_id.ft_project_type', '=', AMC_PROJECT_TYPE),
        ]
        if filters.get('project_id'):
            domain.append(('project_id', '=', int(filters['project_id'])))
        if filters.get('manager_id'):
            domain.append(
                ('project_id.user_id', '=', int(filters['manager_id'])))
        if filters.get('include_closed'):
            # 1_deployed: Deployed, ft_amc_payment_milestone, counts as done
            domain += ['|', ('is_closed', '=', False), ('state', 'in', ['1_done', '1_deployed'])]
        else:
            domain.append(('is_closed', '=', False))
        return domain

    @staticmethod
    def _row_sort_key(row):
        """Most overdue first, then oldest; rows with no overdue days last.

        Name and id close the ordering so two rows with the same figures
        always come back in the same order between two calls.
        """
        overdue = row['overdue_days']
        return (
            overdue is None,
            -(overdue or 0),
            -row['total_days'],
            (row['project_name'] or '').lower(),
            (row['task_name'] or '').lower(),
            row['id'],
        )

    # ------------------------------------------------------------------
    # Public RPC entry points
    # ------------------------------------------------------------------
    @api.model
    def get_filter_options(self):
        """Every live AMC project, for a client that wants a project picker.

        The embedded table has no picker of its own (it follows the Project
        Dashboard's header Project picker, and its search box narrows by
        project name), but the entry point is kept for other callers.

        Searched with the caller's own env, so the list only ever offers
        projects the person may read (record rules apply) — the same
        projects whose tasks get_dashboard_data can return to them.

        Sorted in Python, case-insensitively: a plain ``order='name'`` is a
        collation-dependent SQL sort that puts "abc Ltd" after "Zeta" on a C
        collation, which reads as a broken picker.
        """
        projects = self.env['project.project'].search(self._amc_project_domain())
        return {
            'projects': sorted(
                ({'id': p.id, 'name': p.name or ''} for p in projects),
                key=lambda p: (p['name'].lower(), p['id'])),
        }

    @api.model
    def get_dashboard_data(self, filters=None):
        """The counts and the task table for a set of filters.

        :param filters: ``{'project_id': int|str|None, 'manager_id':
            int|str|None, 'include_closed': bool, 'overdue_only': bool}``.
            Every key may be absent or falsy (= no narrowing); the two ids
            arrive as strings from the dashboard's pickers and as ints from
            Python callers, so they are coerced with int(). ``manager_id`` is
            a res.users id (project.project.user_id); see _task_domain.
        :return: ``{'kpis': {...}, 'rows': [...], 'today': 'YYYY-MM-DD'}``
            (see README for the row fields). ``kpis`` is kept although the
            table no longer shows tiles: the embedded table prints the
            overdue count and the summed overdue days compactly beside its
            toggles, and tests check them against the rows.

        Which deadline
        --------------
        Overdue is measured from the task's ORIGINAL deadline — the first one
        it was given (``pwf_original_deadline``, set once by
        ft_pms_planning_workflow and locked by this module), never the
        latest revision. Revising a deadline therefore never shortens the
        overdue figure; the revision history itself lives in the task's
        Deadline Changes log and chatter. ``original_deadline`` and
        ``deadline`` (the current one) are both in the row so the reader can
        see the drift. ``date_deadline`` only stands in as the reference when
        a task has no original deadline at all (one created before deadline
        tracking that the install hook could not backfill).

        Day arithmetic
        --------------
        Every figure is a count of LOCAL calendar days in the reader's
        timezone (context tz, else the user's, else UTC), mirroring
        ft_task_hours_tracker's ``ft_task_age``. Datetimes are converted
        through project.task._ft_local_date (20:00 UTC is already tomorrow
        in IST, so taking ``.date()`` off the raw value would judge evening
        deadlines by the wrong day).

        * Open task: ``overdue_days`` = today − original deadline day, when
          positive; ``total_days`` = ``ft_task_age`` (days since creation),
          reused so the column can never disagree with Age (Days) on the
          task list.
        * Completed task (``state = '1_done'``): ``overdue_days`` is the
          FROZEN ``ft_historical_overdue_days`` stamped on the task when it
          was completed (days from the original deadline day to the
          completion day; see models/project_task.py) — not recomputed here,
          so the figure is the same in October as it was in September.
          ``total_days`` is the completion day − creation day, so the age
          stops at completion too. ``completed_on`` is the local completion
          day (``date_end``).

        Only a positive overdue count is reported; a task due today, due
        later, with no deadline, or completed on time carries ``None`` so
        the client shows a blank rather than a 0 that reads as "overdue by
        nothing".
        """
        filters = filters or {}
        Task = self.env['project.task']
        today = fields.Date.context_today(self)
        overdue_only = bool(filters.get('overdue_only'))

        # One search in the caller's env (record rules apply), then one pass
        # over the records. project_id, stage_id and user_ids are fetched by
        # the ORM's prefetch for the whole recordset on first access, so the
        # loop issues a handful of queries rather than one per task.
        tasks = Task.search(self._task_domain(filters))
        tasks.fetch(['name', 'project_id', 'stage_id', 'user_ids',
                     'date_deadline', 'pwf_original_deadline', 'date_end',
                     'state', 'create_date', 'ft_historical_overdue_days'])

        rows = []
        for task in tasks:
            deadline = Task._ft_local_date(task.date_deadline)
            original = Task._ft_local_date(task.ft_overdue_reference_deadline())
            completed_on = None
            overdue = None
            if task.is_closed:
                # Frozen at completion: never recomputed from today.
                completed_on = Task._ft_local_date(task.date_end)
                days = int(task.ft_historical_overdue_days or 0)
                created = Task._ft_local_date(task.create_date)
                total_days = max(((completed_on or today) - created).days, 0) \
                    if created else 0
            else:
                days = (today - original).days if original else 0
                total_days = int(task.ft_task_age or 0)
            if days > 0:
                overdue = days
            if overdue_only and overdue is None:
                continue
            rows.append({
                'id': task.id,
                'project_id': task.project_id.id,
                'project_name': task.project_id.name or '',
                'task_name': task.name or '',
                'assignees': ', '.join(
                    name for name in task.user_ids.mapped('name') if name),
                'stage': task.stage_id.name or '',
                'is_closed': bool(task.is_closed),
                'original_deadline':
                    fields.Date.to_string(original) if original else None,
                'deadline': fields.Date.to_string(deadline) if deadline else None,
                'completed_on':
                    fields.Date.to_string(completed_on) if completed_on else None,
                'total_days': total_days,
                'overdue_days': overdue,
            })
        rows.sort(key=self._row_sort_key)

        overdue_rows = [r for r in rows if r['overdue_days'] is not None]
        return {
            'kpis': {
                'total_tasks': len(rows),
                'overdue_tasks': len(overdue_rows),
                'overdue_days': sum(r['overdue_days'] for r in overdue_rows),
                'projects': len({r['project_id'] for r in rows}),
            },
            'rows': rows,
            'today': fields.Date.to_string(today),
        }
