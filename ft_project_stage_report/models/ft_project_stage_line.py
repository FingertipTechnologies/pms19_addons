from collections import defaultdict

from odoo import api, fields, models

from odoo.addons.project_date_extension.models.project_date_extension_request import (
    STAGE_PLANNED_DATE_FIELD,
)

# Context key set by the rebuild while it runs. project.project.write() and
# the request overrides skip their own trigger under it, so a rebuild can
# never start another one (it does not write the project today, but the guard
# costs nothing and protects the next person who adds a write to it).
REBUILD_CONTEXT_KEY = 'ft_stage_report_rebuilding'

# project.project planned-date field -> lower-cased stage key, the reverse of
# project_date_extension's STAGE_PLANNED_DATE_FIELD. That constant pairs each
# stage with the project date by which the project must have REACHED it (its
# planned start: KICKOFF -> date_start, DISC -> kick_start_meeting_date, ...,
# SUPPORT -> support_start_date, CLOSED -> date), the same dates the project
# form and the overdue milestones use. Used here to attribute a legacy request
# raised by DATE only (no stage_to_extend_id) to its stage.
PLANNED_FIELD_STAGE_KEY = {
    fname: key.lower() for key, fname in STAGE_PLANNED_DATE_FIELD.items()
}


class FtProjectStageLine(models.Model):
    """One row per (Implementation project, Implementation stage).

    Every column is a PLAIN stored value filled by ``_rebuild_for_projects``,
    not a compute: Days Worked of the current stage and Overdue Days of the
    next stage not yet reached change every day while nothing on the project
    changes, and the pivot / graph need stored values to aggregate. The rows are system-generated and read-only
    for everybody; they are deleted and recreated by each rebuild.
    """
    _name = 'ft.project.stage.line'
    _description = 'Implementation Project Stage Line'
    _order = 'project_id, sequence, id'

    project_id = fields.Many2one(
        'project.project', string='Project', required=True, index=True,
        ondelete='cascade', readonly=True)
    company_id = fields.Many2one(
        related='project_id.company_id', store=True, readonly=True)
    stage_id = fields.Many2one(
        'project.project.stage', string='Stage', ondelete='set null',
        readonly=True)
    stage_key = fields.Char(
        string='Stage Key', readonly=True,
        help="Lifecycle key of the stage: kickoff, disc, dev, reg, srv, uat, "
             "data, tra, support, closed.")
    sequence = fields.Integer(
        string='Sequence', readonly=True,
        help="Pipeline position of the stage (its sequence).")
    planned_date = fields.Date(
        string='Planned Date', readonly=True,
        help="Date by which the project must reach this stage, as it stands "
             "after approved Date Extensions (the lifecycle date of the same "
             "name on the project form, which a Date Extension Request on "
             "this stage moves).")
    actual_entry_date = fields.Date(
        string='Actual Entry Date', readonly=True,
        help="The date the project first entered this stage. Empty while "
             "it never has.")
    actual_exit_date = fields.Date(
        string='Actual Exit Date', readonly=True,
        help="Entry date of the next stage the project entered. Empty for "
             "the current stage.")
    is_current = fields.Boolean(
        string='Current Stage', readonly=True,
        help="The project is in this stage now.")
    days_worked = fields.Integer(
        string='Days Worked', readonly=True,
        help="Calendar days the project spent in this stage: from its "
             "actual entry date to the actual entry date of the next entered "
             "stage, or to today while it is the current stage. 0 when the "
             "stage was never entered.")
    overdue_days = fields.Integer(
        string='Overdue Days', readonly=True,
        help="Days the stage is late: the Delay Days of the approved Date "
             "Extension Requests that targeted this stage (its Extension "
             "Days). 0 when no extension was approved for the stage.")
    extension_days = fields.Integer(
        string='Extension Days', readonly=True,
        help="Delay Days of the approved Date Extension Requests that "
             "targeted THIS stage. The later dates such a request shifts are "
             "not counted again on their own stages, so the project total is "
             "the plain sum. A preponement counts 0.")

    @api.depends('project_id.name', 'stage_id.name', 'stage_key')
    def _compute_display_name(self):
        for line in self:
            stage = line.stage_id.name or (line.stage_key or '').upper()
            line.display_name = '%s / %s' % (line.project_id.name or '', stage)

    # ------------------------------------------------------------------
    # Rebuild
    # ------------------------------------------------------------------
    @api.model
    def _implementation_projects(self):
        """Every Implementation project, archived ones included (their lines
        would otherwise go stale and never be refreshed). The recordset is
        returned WITHOUT active_test=False in its context: the stage search
        inside _pl_actual_entry_dates must only see live stages."""
        Project = self.env['project.project'].sudo()
        ids = Project.with_context(active_test=False).search(
            [('ft_project_type', '=', 'implementation')]).ids
        return Project.browse(ids)

    @api.model
    def _rebuild_for_projects(self, projects=None):
        """Delete and recreate the lines of ``projects`` (all Implementation
        projects when None, which is what the cron and the install hook
        pass). A project in the set that is not (or no longer) an
        Implementation project simply loses its lines. Runs with sudo; returns
        the lines created."""
        Line = self.sudo().with_context(**{REBUILD_CONTEXT_KEY: True})
        if projects is None:
            projects = self._implementation_projects()
        else:
            projects = projects.sudo().exists()
        if not projects:
            return Line.browse()
        Line.search([('project_id', 'in', projects.ids)]).unlink()
        projects = projects.filtered(
            lambda p: p.ft_project_type == 'implementation')
        if not projects:
            return Line.browse()
        extension = self._approved_extension_days(projects)
        vals_list = []
        for project in projects:
            vals_list.extend(self._prepare_line_vals(project, extension))
        return Line.create(vals_list)

    @api.model
    def _approved_extension_days(self, projects):
        """{(project id, stage key): sum of delay_days} over the APPROVED
        requests of ``projects``, each attributed to the stage it targeted
        (stage_to_extend_id; a legacy date-only request is attributed to the
        stage whose planned date it moved). Only the requested gap of the
        targeted stage is summed, never the downstream shifts it caused, so
        nothing is counted twice. A preponement carries delay_days 0."""
        Request = self.env['project.date.extension.request'].sudo()
        result = defaultdict(int)
        requests = Request.search([
            ('project_id', 'in', projects.ids),
            ('state', '=', 'approved'),
        ])
        for request in requests:
            key = False
            if request.stage_to_extend_id:
                key = request.stage_to_extend_id._ft_stage_key()
            if not key and request.date_to_extend_id:
                key = PLANNED_FIELD_STAGE_KEY.get(
                    request.date_to_extend_id.field_name)
            if key:
                result[(request.project_id.id, key)] += request.delay_days
        return result

    @api.model
    def _planned_date_field(self, key):
        """project.project field holding the date by which the project must
        reach the stage ``key``, or False when there is none / it is not
        installed. Read live from the project: an approved Date Extension
        Request has already moved that field, so the planned dates here are
        the ones after approved extensions."""
        fname = STAGE_PLANNED_DATE_FIELD.get((key or '').upper())
        if fname and fname in self.env['project.project']._fields:
            return fname
        return False

    @api.model
    def _prepare_line_vals(self, project, extension):
        """Line values of one Implementation project, one dict per stage of
        its actual timeline (``_pl_actual_entry_dates``), in pipeline order.

        Planned date: the project date by which the project must have
        REACHED the stage (``STAGE_PLANNED_DATE_FIELD``), read live from the
        project so approved Date Extensions are already in it.

        Exit date of an entered stage: the entry date of the next ENTERED
        stage; empty for the current stage; when nothing later was entered
        although the project sits in a later stage (imported data), the
        current stage's entry date when it is later than this one's, else
        today. Days Worked = exit (today while current) - entry.

        Overdue Days = Extension Days of the stage, nothing else (the
        approved Date Extension Requests are the only source of delay):

        * Extension Days: the Delay Days of the approved Date Extension
          Requests that targeted the stage. The extension a Project Manager
          had to ask for (and an Administrator approved) IS the delay of the
          stage, so it is counted as overdue even though the planned date was
          moved and the stage is then reached "on time";
        * stage with an actual entry date (the current one included):
          ``max(0, entry - planned)`` on top, "the project reached this
          stage N days later than even the extended date";
        * stage not yet entered: only the FIRST such stage AFTER the current
          stage in pipeline order, once its planned date has passed:
          ``today - planned`` on top, "the project should already be in this
          stage" (while no extension has been approved yet). Every other
          unreached stage (a skipped stage before the current one, the later
          future stages) adds nothing, so a late project is not counted once
          per remaining stage;
        * no planned date: nothing on top.

        Example (today 28 Oct, project in SUPPORT, no extensions): Kick-off
        Date 8 Apr, DISC entered 10 Apr -> DISC 2; Data Upload Date 19 Jul,
        DATA entered 15 Sep -> DATA 58; Support Start Date 23 Sep, SUPPORT
        entered 12 Oct -> SUPPORT 19; Closed Date 9 Oct not reached ->
        CLOSED 19; REG never entered (skipped) -> 0. Total 98.
        With extensions: project in DEV, REG had to be reached by 1 Jun; a
        +10 day extension on REG is approved (Regression Date 11 Jun) ->
        REG 10 from the approval on; if REG is then entered on 14 Jun ->
        REG 13 (10 extended + 3 still late).
        """
        project = project.sudo()
        today = fields.Date.context_today(project)
        timeline = project._pl_actual_entry_dates()
        current_key = project.stage_id._ft_stage_key() if project.stage_id else False
        current_index = next(
            (i for i, (key, _stage, _date) in enumerate(timeline)
             if current_key and key == current_key), None)
        current_entry = (
            timeline[current_index][2] if current_index is not None else False)
        vals_list = []
        for index, (key, stage, entry) in enumerate(timeline):
            is_current = bool(current_key) and key == current_key
            planned_field = self._planned_date_field(key)
            planned = project[planned_field] if planned_field else False
            extension_days = extension.get((project.id, key), 0)
            exit_date = False
            days_worked = 0
            if entry:
                if not is_current:
                    exit_date = next(
                        (date for _key, _stage, date in timeline[index + 1:]
                         if date), False)
                    if not exit_date:
                        exit_date = (
                            current_entry
                            if current_entry and current_entry > entry
                            else today)
                reference = exit_date or today
                days_worked = max((reference - entry).days, 0)
            vals_list.append({
                'project_id': project.id,
                'stage_id': stage.id,
                'stage_key': key,
                'sequence': stage.sequence,
                'planned_date': planned or False,
                'actual_entry_date': entry or False,
                'actual_exit_date': exit_date or False,
                'is_current': is_current,
                'days_worked': days_worked,
                # The approved Date Extensions are the stage's delay.
                'overdue_days': extension_days,
                'extension_days': extension_days,
            })
        return vals_list

    # ------------------------------------------------------------------
    # Project Dashboard feed
    # ------------------------------------------------------------------
    @api.model
    def _dashboard_scope_lines(self, scope=None):
        """The lines the Project Dashboard scope selects, plus the closed flag
        of their projects: ``(lines, {project id: closed})``.

        Shared by get_dashboard_rows (flat list) and get_dashboard_matrix
        (one row per project), so the two can never disagree on which
        projects are in scope. ``scope`` carries the board's header filters
        plus the table's own toggle::

            {'project_id': int | False,    # one project, or every one
             'manager_id': int | False,    # res.users id of the Project Manager
             'include_closed': bool}       # keep closed / archived projects

        Only Implementation projects are listed, never templates. A project
        is "closed" when its current stage classifies as the CLOSED lifecycle
        stage (the same stage test the dashboard's own Closed toggle uses) or
        when it is archived: either way delivery is over, so those rows are
        noise by default and come back only with ``include_closed``.

        Runs as the caller (no sudo): the project search applies the
        project.project rules and the line search the line rules, so the
        table never shows more than the list views would.
        """
        scope = scope or {}
        Project = self.env['project.project']
        domain = [('ft_project_type', '=', 'implementation')]
        # Templates (core project >= 18) are blueprints, not deliveries;
        # guarded by name so the method does not depend on the field.
        if 'is_template' in Project._fields:
            domain.append(('is_template', '=', False))
        if scope.get('project_id'):
            domain.append(('id', '=', int(scope['project_id'])))
        if scope.get('manager_id'):
            domain.append(('user_id', '=', int(scope['manager_id'])))
        # active_test=False: an archived project still has lines (the rebuild
        # keeps them fresh) and is listed under "Include closed".
        projects = Project.with_context(active_test=False).search(domain)
        if not projects:
            return self.browse(), {}

        # One stage-name classification per stage, not per project.
        closed_by_stage = {}

        def project_closed(project):
            stage = project.stage_id
            if stage and stage.id not in closed_by_stage:
                closed_by_stage[stage.id] = stage._ft_stage_key() == 'closed'
            return (not project.active) or bool(
                stage and closed_by_stage[stage.id])

        closed = {p.id: project_closed(p) for p in projects}
        if not scope.get('include_closed'):
            projects = projects.filtered(lambda p: not closed[p.id])
            if not projects:
                return self.browse(), closed
        return self.search([('project_id', 'in', projects.ids)]), closed

    @api.model
    def get_dashboard_rows(self, scope=None):
        """Flat rows of the Implementation Stages data, one per (project,
        stage), in display order: by project name, then by pipeline position
        of the stage. ``scope`` as in ``_dashboard_scope_lines``.

        Kept for the list-shaped consumers (and the tests); the dashboard
        table itself reads ``get_dashboard_matrix`` since 19.0.1.2.0. Dates
        are ISO strings (sortable as plain text) or False.
        """
        lines, closed = self._dashboard_scope_lines(scope)
        to_iso = fields.Date.to_string
        rows = []
        for line in lines:
            project = line.project_id
            rows.append({
                'id': line.id,
                'project_id': project.id,
                'project_name': project.name or '',
                'stage_name': line.stage_id.name or (line.stage_key or '').upper(),
                'sequence': line.sequence,
                'planned_date': to_iso(line.planned_date) if line.planned_date else False,
                'actual_entry_date': (to_iso(line.actual_entry_date)
                                      if line.actual_entry_date else False),
                'actual_exit_date': (to_iso(line.actual_exit_date)
                                     if line.actual_exit_date else False),
                'is_current': line.is_current,
                'days_worked': line.days_worked,
                'overdue_days': line.overdue_days,
                'extension_days': line.extension_days,
                'project_closed': closed[project.id],
            })
        # Pre-sorted here because a one-key client sort (DataTable) on
        # project_name is stable, so the stage order within a project is
        # whatever arrives, i.e. this.
        rows.sort(key=lambda r: (r['project_name'].lower(), r['project_id'],
                                 r['sequence'], r['id']))
        return rows

    @api.model
    def get_dashboard_matrix(self, scope=None):
        """The "Implementation Stages" matrix of the Project Dashboard: one
        row per project, one column per lifecycle stage. ``scope`` as in
        ``_dashboard_scope_lines``. Returns::

            {'stages': [{'id', 'name', 'sequence'}, ...],   # pipeline order
             'projects': [{
                 'project_id', 'project_name', 'manager_name',
                 'project_closed', 'current_stage_id',
                 'total_days_worked', 'total_overdue_days', 'is_overdue',
                 'cells': {str(stage id): {
                     'days_worked', 'overdue_days', 'extension_days',
                     'planned_date', 'actual_entry_date', 'actual_exit_date',
                     'is_current',
                     'reached',          # the stage has an actual entry date
                 }},
             }, ...]}                                        # by project name

        The stage columns are the distinct stages of the lines in scope (a
        project missing a line for a stage simply has no cell for it, which
        the client renders as "—"), ordered by the stored line sequence so a
        later reorder of the stages shows up at the next rebuild, like every
        other number. ``cells`` is keyed by the stage id as a STRING because
        it travels as JSON, where keys are strings anyway; a line whose stage
        was deleted (ondelete='set null', until the nightly rebuild drops it)
        is keyed by its stage key instead so the column still exists.
        """
        lines, closed = self._dashboard_scope_lines(scope)
        to_iso = fields.Date.to_string

        def stage_ident(line):
            return line.stage_id.id or (line.stage_key or '')

        stages = {}
        by_project = defaultdict(list)
        for line in lines:
            ident = stage_ident(line)
            if ident not in stages:
                stages[ident] = {
                    'id': ident,
                    'name': line.stage_id.name or (line.stage_key or '').upper(),
                    'sequence': line.sequence,
                }
            by_project[line.project_id].append(line)

        projects = []
        for project, project_lines in by_project.items():
            cells = {}
            current_stage_id = False
            for line in project_lines:
                ident = stage_ident(line)
                if line.is_current:
                    current_stage_id = ident
                cells[str(ident)] = {
                    'days_worked': line.days_worked,
                    'overdue_days': line.overdue_days,
                    'extension_days': line.extension_days,
                    'planned_date': (to_iso(line.planned_date)
                                     if line.planned_date else False),
                    'actual_entry_date': (to_iso(line.actual_entry_date)
                                          if line.actual_entry_date else False),
                    'actual_exit_date': (to_iso(line.actual_exit_date)
                                         if line.actual_exit_date else False),
                    'is_current': line.is_current,
                    'reached': bool(line.actual_entry_date),
                }
            total_overdue = sum(ln.overdue_days for ln in project_lines)
            projects.append({
                'project_id': project.id,
                'project_name': project.name or '',
                'manager_name': project.user_id.name or '',
                'project_closed': closed[project.id],
                'current_stage_id': current_stage_id,
                'total_days_worked': sum(ln.days_worked for ln in project_lines),
                'total_overdue_days': total_overdue,
                'is_overdue': total_overdue > 0,
                'cells': cells,
            })
        projects.sort(key=lambda p: (p['project_name'].lower(), p['project_id']))
        return {
            'stages': sorted(stages.values(),
                             key=lambda s: (s['sequence'], s['name'], str(s['id']))),
            'projects': projects,
        }

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------
    def action_refresh(self):
        """Header button of the report list: rebuild every Implementation
        project now (the selection, if any, is ignored: the numbers of one
        project are never fresher than the others'). The list reloads
        itself once the action returns."""
        self._rebuild_for_projects()
        return True
