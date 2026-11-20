# -*- coding: utf-8 -*-
"""Spreadsheet exports (plain HTTP downloads cannot go through call_kw).

Every export calls the same ``adoption.dashboard`` methods as the screens, as
the logged-in user, so it can never return more than the screen would show.
"""
import io
import re

from odoo import http
from odoo.http import request

XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def _xlsx(title, headers, rows, widths=None):
    import xlsxwriter
    out = io.BytesIO()
    book = xlsxwriter.Workbook(out, {'in_memory': True})
    sheet = book.add_worksheet(re.sub(r'[\[\]:*?/\\]', '', title)[:31] or 'Adoption')
    head = book.add_format({'bold': True, 'bg_color': '#7C3AED', 'font_color': '#FFFFFF', 'border': 1})
    for col, text in enumerate(headers):
        sheet.write(0, col, text, head)
        sheet.set_column(col, col, (widths or {}).get(col, max(12, min(40, len(text) + 4))))
    for r, row in enumerate(rows, 1):
        for c, value in enumerate(row):
            sheet.write(r, c, value if value is not None else '')
    sheet.freeze_panes(1, 0)
    book.close()
    return out.getvalue()


def _download(data, filename):
    safe = re.sub(r'[^A-Za-z0-9._-]', '_', filename)
    return request.make_response(data, headers=[
        ('Content-Type', XLSX_MIME),
        ('Content-Disposition', 'attachment; filename="%s"' % safe),
        ('Cache-Control', 'no-store'),
    ])


class AdoptionController(http.Controller):

    @http.route('/adoption/export/leaderboard.xlsx', type='http', auth='user', methods=['GET'])
    def export_leaderboard(self, period_start=None, period_type='month', **_kw):
        data = request.env['adoption.dashboard'].get_leaderboard(period_start, period_type)
        headers = ['Rank', 'Employee', 'Score', 'Band', 'Active days', 'Created', 'Updated',
                   'Meaningful edits', 'Active minutes', 'Presence', 'Data activity',
                   'Process compliance', 'Feature adoption', 'Engagement', 'Data quality']
        rows = [[r['rank'], r['name'], r['total_score'], r['band_label'], r['active_days'],
                 r['records_created'], r['records_updated'], r['meaningful_edits'], r['active_minutes'],
                 *[r['components'][c] for c in ('presence', 'data_activity', 'process_compliance',
                                                'feature_adoption', 'engagement', 'data_quality')]]
                for r in data['rows']]
        return _download(_xlsx('Leaderboard', headers, rows), 'AdoptionLeaderboard_%s.xlsx' % data['period']['start'])

    @http.route('/adoption/export/fields.xlsx', type='http', auth='user', methods=['GET'])
    def export_fields(self, model_name=None, date_from=None, date_to=None, user_id=None, **_kw):
        data = request.env['adoption.dashboard'].get_field_adoption(
            model_name or None, date_from, date_to, int(user_id) if user_id else None)
        headers = ['Model', 'Field', 'Technical name', 'Meaningful', 'Edits', 'Distinct users',
                   'Coverage %', 'Last changed', 'Category']
        rows = [[r['model_label'], r['label'], r['field'], 'Yes' if r['meaningful'] else '', r['edits'],
                 r['users'], r['coverage'], r['last_changed'], r['category']] for r in data['rows']]
        rows += [[r['model_label'], r['label'], r['field'], 'Yes' if r['meaningful'] else '', 0, 0, 0, '',
                  'UNUSED (observed)'] for r in data['unused']]
        rows += [[r['model_label'], r['label'], r['field'], 'Yes' if r['meaningful'] else '', '', '', '', '',
                  'UNKNOWN (%s)' % r['status']] for r in data['unknown']]
        return _download(_xlsx('Field adoption', headers, rows), 'AdoptionFields_%s.xlsx' % (model_name or 'all_models'))

    @http.route('/adoption/export/user.xlsx', type='http', auth='user', methods=['GET'])
    def export_user(self, user_id=None, date_from=None, date_to=None, **_kw):
        data = request.env['adoption.dashboard'].get_user_explorer(
            int(user_id) if user_id else None, date_from, date_to, limit=500)
        headers = ['When', 'Model', 'Record', 'Operation', 'Type', 'Source', 'Automated', 'Fields changed', 'Meaningful']
        rows = [[a['when'], a['model'], a['record'], a['operation'], a['type'], a['source'],
                 'Yes' if a['automated'] else '', a['changes'], a['meaningful']] for a in data['activity']]
        return _download(_xlsx('User activity', headers, rows), 'AdoptionUser_%s.xlsx' % data['user']['id'])

    # ------------------------------------------------------------------ new screens
    @staticmethod
    def _uid(user_id):
        return int(user_id) if user_id else None

    @http.route('/adoption/export/activity.xlsx', type='http', auth='user', methods=['GET'])
    def export_activity(self, date_from=None, date_to=None, user_id=None, model_name=None, operation=None,
                        source=None, origin=None, search=None, **_kw):
        data = request.env['adoption.dashboard'].get_activity_log(
            date_from=date_from, date_to=date_to, user_id=self._uid(user_id), model_name=model_name,
            operation=operation, source=source, origin=origin, search=search, limit=5000, export=True)
        headers = ['When (UTC)', 'User', 'Model', 'Record', 'Operation', 'Category', 'Source', 'Automated',
                   'Fields changed', 'Meaningful', 'Points', 'Transaction']
        rows = [[r['when'], r['user'], r['model'], r['record'], r['operation'], r['type'], r['source'],
                 'Yes' if r['automated'] else '', r['changes'], r['meaningful'], r['points'], r['transaction']]
                for r in data['rows']]
        return _download(_xlsx('Activity log', headers, rows), 'AdoptionActivity_%s.xlsx' % data['range']['from'])

    @http.route('/adoption/export/summary.xlsx', type='http', auth='user', methods=['GET'])
    def export_summary(self, date_from=None, date_to=None, user_id=None, model_name=None, granularity='day', **_kw):
        data = request.env['adoption.dashboard'].get_summary_report(
            date_from=date_from, date_to=date_to, user_id=self._uid(user_id), model_name=model_name,
            granularity=granularity)
        keys = ['active_users', 'created', 'updated', 'deleted', 'viewed', 'field_edits', 'meaningful',
                'automated', 'points', 'pages', 'reports', 'dashboards', 'searches', 'active_minutes', 'logins']
        headers = ['Period'] + [k.replace('_', ' ').title() for k in keys]
        rows = [[r['label']] + [r[k] for k in keys] for r in data['rows']]
        rows.append(['TOTAL'] + [data['totals'][k] for k in keys])
        return _download(_xlsx('Summary %s' % data['granularity'], headers, rows),
                         'AdoptionSummary_%s_%s.xlsx' % (data['granularity'], data['range']['from']))

    @http.route('/adoption/export/field_changes.xlsx', type='http', auth='user', methods=['GET'])
    def export_field_changes(self, date_from=None, date_to=None, user_id=None, model_name=None,
                             meaningful_only=None, include_automated=None, kind=None, **_kw):
        data = request.env['adoption.dashboard'].get_field_change_report(
            date_from=date_from, date_to=date_to, user_id=self._uid(user_id), model_name=model_name,
            meaningful_only=meaningful_only in ('1', 'true', 'True'),
            include_automated=include_automated in ('1', 'true', 'True'), kind=kind, limit=5000, export=True)
        headers = ['When (UTC)', 'User', 'Model', 'Record', 'Field', 'Old value', 'New value', 'Kind',
                   'Meaningful', 'Automated']
        rows = [[r['when'], r['user'], r['model'], r['record'], r['field'], r['old'], r['new'], r['kind'],
                 'Yes' if r['meaningful'] else '', 'Yes' if r['automated'] else ''] for r in data['rows']]
        return _download(_xlsx('Field changes', headers, rows), 'AdoptionFieldChanges_%s.xlsx' % data['range']['from'])
