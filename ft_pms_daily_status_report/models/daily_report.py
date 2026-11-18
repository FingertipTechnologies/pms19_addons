import io
import logging
from collections import defaultdict
from datetime import datetime

from odoo import _, api, fields, models, Command
from odoo.tools.misc import format_date

_logger = logging.getLogger(__name__)

LOG_MODEL = 'ft.pms.daily.report.log'

IMPL_HEADERS = ['Project', 'Project Manager', 'Technical Lead', 'Current Stage',
                'Days Worked', 'Overdue Days', 'Overdue Stages']
AMC_HEADERS = ['Project', 'Task', 'Assignees', 'Stage', 'Original Deadline',
               'Current Deadline', 'Total Days', 'Overdue Days']


class FtPmsDailyReport(models.AbstractModel):
    """Builds and sends the daily Implementation + AMC status e-mail.

    The figures are NOT computed here: the Implementation section is
    ft.project.stage.line.get_dashboard_matrix (the "Implementation Stages"
    matrix of the Project Dashboard) and the AMC section is
    ft.amc.overdue.dashboard.get_dashboard_data (the "AMC Task Overdue"
    table), both called with their dashboard defaults (closed projects /
    completed tasks excluded), so the e-mail always agrees with the boards.
    Both providers run under sudo so the content never depends on who
    triggers the send (the cron runs as OdooBot).
    """
    _name = 'ft.pms.daily.report'
    _description = 'PMS Daily Implementation and AMC Status Report'

    # ------------------------------------------------------------------
    # Context helpers
    # ------------------------------------------------------------------
    @api.model
    def _report_company(self):
        return (self.env.ref('base.main_company', raise_if_not_found=False)
                or self.env.company)

    @api.model
    def _report_date(self, company=None):
        company = company or self._report_company()
        return datetime.now(company._ft_daily_report_tz()).date()

    @api.model
    def _base_url(self):
        return (self.env['ir.config_parameter'].sudo().get_param('web.base.url')
                or '').rstrip('/')

    @api.model
    def _project_url(self, project_id):
        return "%s/odoo/project/%s" % (self._base_url(), project_id)

    @api.model
    def _task_url(self, project_id, task_id):
        return "%s/odoo/project/%s/tasks/%s" % (self._base_url(), project_id, task_id)

    @api.model
    def _recipient_users(self, project):
        """Project Manager only (internal, active users)."""
        return project.user_id.filtered(
            lambda u: u.active and not u.share
        )

    # ------------------------------------------------------------------
    # Data (reused from the dashboards)
    # ------------------------------------------------------------------
    @api.model
    def _collect_implementation(self):
        """{project.project: row} for every live Implementation project."""
        matrix = self.env['ft.project.stage.line'].sudo().get_dashboard_matrix(
            {'include_closed': False})
        stage_name = {str(s['id']): s['name'] for s in matrix['stages']}
        stage_seq = {str(s['id']): s['sequence'] for s in matrix['stages']}
        Project = self.env['project.project'].sudo().with_context(active_test=False)
        projects = Project.browse([p['project_id'] for p in matrix['projects']])
        projects.fetch(['name', 'user_id', 'technical_lead_id', 'stage_id'])
        rows = {}
        for data in matrix['projects']:
            project = Project.browse(data['project_id'])
            overdue_cells = sorted(
                ((key, cell['overdue_days']) for key, cell in data['cells'].items()
                 if cell['overdue_days'] > 0),
                key=lambda kc: (stage_seq.get(kc[0], 0), kc[0]))
            current_key = (str(data['current_stage_id'])
                           if data['current_stage_id'] else '')
            rows[project] = {
                'project_id': project.id,
                'name': data['project_name'],
                'url': self._project_url(project.id),
                'manager': project.user_id.name or '',
                'tech_lead': project.technical_lead_id.name or '',
                'current_stage': (stage_name.get(current_key)
                                  or project.stage_id.name or ''),
                'total_days_worked': data['total_days_worked'],
                'total_overdue_days': data['total_overdue_days'],
                'is_overdue': data['is_overdue'],
                'overdue_stages': ', '.join(
                    "%s %sd" % (stage_name.get(key, key), days)
                    for key, days in overdue_cells),
            }
        return rows

    @api.model
    def _collect_amc(self):
        """{project.project: [task rows]} for every open task of a live AMC
        project, in the dashboard's order (most overdue first)."""
        data = self.env['ft.amc.overdue.dashboard'].sudo().get_dashboard_data(
            {'include_closed': False, 'overdue_only': False})
        by_project_id = defaultdict(list)
        for row in data['rows']:
            row = dict(row)
            row['project_url'] = self._project_url(row['project_id'])
            row['task_url'] = self._task_url(row['project_id'], row['id'])
            row['is_overdue'] = row['overdue_days'] is not None
            by_project_id[row['project_id']].append(row)
        Project = self.env['project.project'].sudo()
        projects = Project.browse(list(by_project_id))
        projects.fetch(['name', 'user_id', 'technical_lead_id'])
        return {project: by_project_id[project.id] for project in projects}

    @api.model
    def _build_payloads(self, users=None, report_date=None, company=None):
        """One payload per recipient: {res.users: payload}.

        Without ``users`` every PM / Technical Lead holding at least one
        project in scope gets one. With ``users`` (wizard / retry) exactly
        those users get one, each still limited to their own projects, even
        when that leaves both sections empty.
        """
        company = company or self._report_company()
        report_date = report_date or self._report_date(company)
        tz = company._ft_daily_report_tz().zone
        this = self.with_context(tz=tz)
        impl = this._collect_implementation()
        amc = this._collect_amc()
        limit = max(company.daily_report_xlsx_row_limit or 50, 1)

        per_user = {}

        def bucket(user):
            if user not in per_user:
                per_user[user] = {'implementation': [], 'amc': []}
            return per_user[user]

        if users:
            for user in users:
                bucket(user)
        for project, row in impl.items():
            for user in self._recipient_users(project):
                if users and user not in users:
                    continue
                bucket(user)['implementation'].append(row)
        for project, task_rows in amc.items():
            for user in self._recipient_users(project):
                if users and user not in users:
                    continue
                bucket(user)['amc'].extend(task_rows)

        payloads = {}
        for user, data in per_user.items():
            impl_rows = sorted(
                data['implementation'],
                key=lambda r: (-r['total_overdue_days'], r['name'].lower()))
            amc_rows = sorted(
                data['amc'],
                key=lambda r: (r['overdue_days'] is None, -(r['overdue_days'] or 0),
                               r['project_name'].lower(), r['task_name'].lower()))
            impl_overdue = [r for r in impl_rows if r['is_overdue']]
            amc_overdue = [r for r in amc_rows if r['is_overdue']]
            payloads[user] = {
                'user': user,
                'user_name': user.name,
                'report_date': report_date,
                'date_str': format_date(self.env, report_date, lang_code=user.lang),
                'row_limit': limit,
                'implementation': {
                    'rows': impl_rows,
                    'count': len(impl_rows),
                    'overdue_count': len(impl_overdue),
                    'overdue_days': sum(r['total_overdue_days'] for r in impl_overdue),
                    'attach': len(impl_rows) > limit,
                },
                'amc': {
                    'rows': amc_rows,
                    'project_count': len({r['project_id'] for r in amc_rows}),
                    'count': len(amc_rows),
                    'overdue_count': len(amc_overdue),
                    'overdue_days': sum(r['overdue_days'] for r in amc_overdue),
                    'attach': len(amc_rows) > limit,
                },
            }
        return payloads

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    @api.model
    def _subject(self, report_date, lang=None):
        return _("Daily Project Status Report – %s",
                 format_date(self.env, report_date, lang_code=lang))

    @api.model
    def _render_body(self, payload):
        return str(self.env['ir.qweb'].sudo()._render(
            'ft_pms_daily_status_report.email_body', dict(payload)))

    @api.model
    def _xlsx_bytes(self, sheet_name, headers, rows, values_of, overdue_of, widths):
        import xlsxwriter  # Odoo requirement; imported lazily like report_xlsx
        buffer = io.BytesIO()
        workbook = xlsxwriter.Workbook(buffer, {'in_memory': True})
        sheet = workbook.add_worksheet(sheet_name[:31])
        header_fmt = workbook.add_format({'bold': True, 'bg_color': '#DDDDDD', 'border': 1})
        red_fmt = workbook.add_format({'font_color': '#B00020', 'bold': True})
        for col, title in enumerate(headers):
            sheet.write(0, col, title, header_fmt)
        for col, width in enumerate(widths):
            sheet.set_column(col, col, width)
        for line, row in enumerate(rows, start=1):
            fmt = red_fmt if overdue_of(row) else None
            for col, value in enumerate(values_of(row)):
                sheet.write(line, col, '' if value is None else value, fmt)
        sheet.freeze_panes(1, 0)
        workbook.close()
        return buffer.getvalue()

    @api.model
    def _build_attachments(self, payload, log):
        """Excel file(s) for the sections over the row limit, owned by the
        log so they stay readable from it."""
        Attachment = self.env['ir.attachment'].sudo()
        date_tag = fields.Date.to_string(payload['report_date'])
        attachments = Attachment
        if payload['implementation']['attach']:
            data = self._xlsx_bytes(
                'Implementation', IMPL_HEADERS, payload['implementation']['rows'],
                lambda r: [r['name'], r['manager'], r['tech_lead'], r['current_stage'],
                           r['total_days_worked'], r['total_overdue_days'],
                           r['overdue_stages']],
                lambda r: r['is_overdue'],
                [40, 24, 24, 18, 12, 12, 40])
            attachments |= Attachment.create({
                'name': 'Implementation_Projects_%s.xlsx' % date_tag,
                'raw': data,
                'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'res_model': LOG_MODEL,
                'res_id': log.id,
            })
        if payload['amc']['attach']:
            data = self._xlsx_bytes(
                'AMC Tasks', AMC_HEADERS, payload['amc']['rows'],
                lambda r: [r['project_name'], r['task_name'], r['assignees'], r['stage'],
                           r['original_deadline'] or '', r['deadline'] or '',
                           r['total_days'], r['overdue_days']],
                lambda r: r['is_overdue'],
                [36, 48, 28, 18, 16, 16, 12, 12])
            attachments |= Attachment.create({
                'name': 'AMC_Tasks_%s.xlsx' % date_tag,
                'raw': data,
                'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'res_model': LOG_MODEL,
                'res_id': log.id,
            })
        return attachments

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------
    @api.model
    def _send_one(self, log, payload, company):
        """Build the e-mail of one log and put it in the mail queue."""
        user = log.user_id
        email_from = company._ft_daily_report_email_from()
        old_mail = log.mail_id.sudo()
        if old_mail and old_mail.state == 'exception':
            old_mail.cancel()
        log.attachment_ids.sudo().unlink()
        attachments = self._build_attachments(payload, log)
        mail = self.env['mail.mail'].sudo().create({
            'subject': self._subject(payload['report_date'], user.lang),
            'body_html': self._render_body(payload),
            'email_from': email_from,
            'reply_to': email_from,
            'email_to': user.email_formatted,
            'email_cc': 'shebin@fingertipplus.com, ameen@fingertipplus.com, sunil@fingertipplus.com, rakesh@fingertipplus.com',
            'author_id': self.env.user.partner_id.id,
            'model': LOG_MODEL,
            'res_id': log.id,
            'auto_delete': False,
            'attachment_ids': [Command.set(attachments.ids)],
        })
        log.write({
            'mail_id': mail.id,
            'state': 'queued',
            'error': False,
            'sent_on': False,
            'implementation_count': payload['implementation']['count'],
            'amc_task_count': payload['amc']['count'],
        })
        return mail

    @api.model
    def send_daily_reports(self, users=None, force=False, report_date=None,
                           force_send=False):
        """Send today's report to ``users`` (every PM / Technical Lead with a
        project in scope when None). Returns the logs touched.

        * dedupe: a (user, day) already queued or sent is skipped unless
          ``force``; a failed one is rebuilt and resent;
        * ``force_send``: deliver immediately (wizard / retry) instead of
          waiting for the mail queue cron.
        """
        company = self._report_company()
        report_date = report_date or self._report_date(company)
        Log = self.env[LOG_MODEL].sudo()
        payloads = self._build_payloads(users=users, report_date=report_date,
                                        company=company)
        logs = Log
        mails = self.env['mail.mail'].sudo()
        for user, payload in payloads.items():
            # Nothing to report (no Implementation project and no AMC task):
            # no e-mail at all. A section that is empty is simply left out
            # of the body by the template.
            if not payload['implementation']['rows'] and not payload['amc']['rows']:
                _logger.info(
                    "Daily status report: nothing to report for %s (%s), skipped.",
                    user.name, report_date)
                continue
            log = Log.search([('user_id', '=', user.id),
                              ('report_date', '=', report_date)], limit=1)
            if log and log.state in ('queued', 'sent') and not force:
                continue
            if not log:
                log = Log.create({'user_id': user.id, 'report_date': report_date})
            logs |= log
            if not user.email:
                log.write({'state': 'failed', 'mail_id': False,
                           'error': _("The user has no e-mail address.")})
                continue
            try:
                with self.env.cr.savepoint():
                    mails |= self._send_one(log, payload, company)
            except Exception as exc:  # noqa: BLE001 - logged on the record
                _logger.exception(
                    "Daily status report for %s (%s) failed.", user.name, report_date)
                log.write({'state': 'failed', 'mail_id': False, 'error': str(exc)})
        if force_send and mails:
            mails.send(raise_exception=False)
            logs._sync_mail_state()
        return logs

    # ------------------------------------------------------------------
    # Cron
    # ------------------------------------------------------------------
    @api.model
    def _cron_send_daily_reports(self):
        """PMS: Send Daily Implementation and AMC Reports (daily, at the
        company's send hour)."""
        Log = self.env[LOG_MODEL].sudo()
        Log.search([('state', '=', 'queued')])._sync_mail_state()
        # Days Worked / Overdue Days of the current stage grow daily; make
        # sure the stored lines are today's before reading them.
        self.env['ft.project.stage.line'].sudo()._rebuild_for_projects()
        logs = self.send_daily_reports()
        _logger.info("Daily status report: %s recipient(s) processed.", len(logs))
        return True
