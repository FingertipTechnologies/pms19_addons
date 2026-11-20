# -*- coding: utf-8 -*-
"""Server-side "Download PDF" for the dashboard screens.

Each builder calls the SAME ``adoption.dashboard`` methods the screens call, as the
logged-in user, so the PDF can never contain more than the screen would show:
scope (own data vs. organisation) and record rules are enforced by those methods.
The browser only sends a whitelisted set of options; nothing in ``data`` is trusted
as an id, a domain or a user.

Charts are rendered as tables / simple bars: wkhtmltopdf has no support for the
conic gradients used on screen.
"""
import re
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services import report_utils as ru

SCREENS = ('overview', 'leaderboard', 'user', 'fields', 'navigation', 'activity', 'models', 'reports')
MODEL_RE = re.compile(r'^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$')
TITLES = {
    'overview': 'Overview', 'leaderboard': 'Leaderboard', 'user': 'User adoption', 'fields': 'Field adoption',
    'navigation': 'Navigation', 'activity': 'Activity log', 'models': 'Model analytics', 'reports': 'Reports',
}
BAND = {'power_user': 'Power User', 'healthy': 'Healthy', 'needs_improvement': 'Needs Improvement',
        'at_risk': 'At Risk', 'inactive': 'Inactive'}


def _clean(value):
    """The options arrive through a URL: JSON null/false may come back as strings."""
    if value in (None, False, '', 'false', 'False', 'null', 'None', 'undefined'):
        return None
    return value


def table(title, columns, rows, note=None, numeric=()):
    return {'kind': 'table', 'title': title, 'columns': columns, 'rows': rows, 'note': note,
            'numeric': list(numeric)}


def bars(title, items, suffix=''):
    top = max([float(i[1] or 0) for i in items] or [0])
    return {'kind': 'bars', 'title': title, 'suffix': suffix,
            'items': [{'label': i[0], 'text': ru.fmt_num(i[1]) + suffix, 'pct': ru.share_of_top(i[1], top)}
                      for i in items]}


class ReportAdoptionScreen(models.AbstractModel):
    _name = 'report.adoption_intelligence.report_screen'
    _description = 'Adoption Dashboard Screen (PDF)'

    # ------------------------------------------------------------------ entry point
    @api.model
    def _get_report_values(self, docids, data=None):
        data = data or {}
        screen = data.get('screen')
        if screen not in SCREENS:
            raise UserError(_('Unknown report screen.'))
        params = self._params(data)
        doc = getattr(self, '_build_%s' % screen)(params)
        scope = self._scope_label(params)
        doc.update({
            'title': TITLES[screen], 'scope': scope,
            'range': '%s \u2192 %s' % (params['date_from'], params['date_to']) if screen != 'leaderboard' else '',
            'generated': fields.Datetime.to_string(fields.Datetime.now()),
            'user': self.env.user.name,
        })
        return {'doc_ids': docids or [], 'doc_model': False, 'docs': [doc], 'doc': doc, 'data': data}

    @api.model
    def _params(self, data):
        def to_date(value):
            value = _clean(value)
            try:
                return fields.Date.to_date(value) if value else None
            except (ValueError, TypeError):
                return None

        end = to_date(data.get('date_to')) or fields.Date.context_today(self)
        start = to_date(data.get('date_from')) or end - timedelta(days=89)
        uid = _clean(data.get('user_id'))
        try:
            uid = int(uid) if uid else None
        except (TypeError, ValueError):
            uid = None
        model = _clean(data.get('model_name'))
        model = model if isinstance(model, str) and MODEL_RE.match(model) else None
        gran = data.get('granularity')
        return {
            'date_from': start, 'date_to': end, 'user_id': uid, 'model_name': model,
            'granularity': gran if gran in ru.GRANULARITIES else 'month',
            'period_start': to_date(data.get('period_start')) or end,
        }

    @api.model
    def _scope_label(self, p):
        D = self.env['adoption.dashboard']
        if p['user_id']:
            return self.env['res.users'].sudo().browse(p['user_id']).name or ''
        return _('All users (org)') if D._flags()['is_manager'] else _('My activity')

    @property
    def D(self):
        return self.env['adoption.dashboard']

    def _kw(self, p, *names):
        mapping = {'date_from': p['date_from'], 'date_to': p['date_to'], 'user_id': p['user_id'], 'model_name': p['model_name']}
        return {k: mapping[k] for k in names}

    # ------------------------------------------------------------------ builders
    @api.model
    def _build_overview(self, p):
        d = self.D.get_overview(**self._kw(p, 'date_from', 'date_to', 'user_id', 'model_name'))
        k = d['kpis']
        kpis = [
            ('Adoption score', ru.fmt_num(k['avg_score']) if k['avg_score'] is not None else '\u2014'),
            ('Active users', '%s / %s' % (k['active_users'], k['total_users'])), ('Users at risk', k['users_at_risk']),
            ('Activity events', ru.fmt_num(k['events_total'])),
            ('Created / updated / deleted', '%s / %s / %s' % (k['crud']['created'], k['crud']['updated'], k['crud']['deleted'])),
            ('Field edits', '%s (%s meaningful)' % (ru.fmt_num(k['field_edits']), ru.fmt_num(k['meaningful_edits']))),
            ('Estimated active time', '%s min' % ru.fmt_num(k['active_minutes'])), ('Logins', ru.fmt_num(k['logins'])),
            ('User-initiated share', '%s%%' % k['human_pct']),
        ]
        trend = [(t['date'], t['events'], t['field_edits'], t['active_minutes']) for t in d['trend']
                 if t['events'] or t['field_edits'] or t['active_minutes']][:120]
        return {'subtitle': 'Adoption health, activity and trends.', 'kpis': kpis, 'sections': [
            table('Model detail', ['Model', 'Created', 'Updated', 'Deleted', 'Viewed', 'Field edits', 'Users'],
                  [[o['label'], o['created'], o['updated'], o['deleted'], o['viewed'], o['field_edits'], o['users']]
                   for o in d['objects']], numeric=range(1, 7)),
            bars('Adoption bands (users)', [(BAND[b], n) for b, n in d['bands'].items()]),
            bars('Organisation health', [(f['label'], f['value']) for f in d['factors']], '%'),
            table('Recommended actions', ['Impact', 'Action', 'Why'], [[i['impact'], i['title'], i['detail']] for i in d['insights']]),
            table('Daily trend', ['Date', 'Events', 'Field edits', 'Active minutes'], trend, numeric=range(1, 4)),
        ]}

    @api.model
    def _build_leaderboard(self, p):
        d = self.D.get_leaderboard(period_start=p['period_start'], period_type='month')
        return {'subtitle': 'Month of %s (score weights: presence 15, data activity 20, process compliance 25, '
                            'feature adoption 15, engagement 15, data quality 10).' % d['period']['start'][:7],
                'kpis': [('Period', '%s \u2192 %s' % (d['period']['start'], d['period']['end'])),
                         ('Scored users', len(d['rows'])), ('Final', 'yes' if d['is_final'] else 'in progress')],
                'sections': [
                    table('Adoption score', ['#', 'Employee', 'Score', 'Band', 'Active days', 'Created', 'Updated', 'Meaningful edits', 'Active min'],
                          [[r['rank'], r['name'], r['total_score'], r['band_label'], r['active_days'], r['records_created'],
                            r['records_updated'], r['meaningful_edits'], ru.fmt_num(r['active_minutes'])] for r in d['rows']],
                          numeric=[0, 2, 4, 5, 6, 7, 8]),
                    table('Points ranking', ['#', 'Employee', 'Points', 'Created', 'Updated', 'Pages'],
                          [[r['rank'], r['name'], r['points'], r['created'], r['updated'], r['pages']] for r in d['points']],
                          numeric=range(0, 6)),
                ]}

    @api.model
    def _build_user(self, p):
        d = self.D.get_user_explorer(user_id=p['user_id'], date_from=p['date_from'], date_to=p['date_to'],
                                     model_name=p['model_name'], limit=60)
        k, score = d['kpis'], d['score']
        kpis = [('User', d['user']['name']), ('Created', k['created']), ('Updated', k['updated']), ('Deleted', k['deleted']),
                ('Records viewed', k['viewed']), ('Field edits', '%s (%s meaningful)' % (k['field_edits'], k['meaningful_edits'])),
                ('Active days', k['active_days']), ('Logins', k['logins']), ('Reports / dashboards', '%s / %s' % (k['reports'], k['dashboards'])),
                ('Active time', '%s min' % ru.fmt_num(k['active_minutes'])), ('Automated changes', k['automated'])]
        if score:
            kpis.insert(1, ('Adoption score', '%s (%s)' % (ru.fmt_num(score['total']), score['band_label'])))
        sections = []
        if score:
            sections.append(table('Score breakdown (weighted points)', ['Component', 'Points', 'Max'],
                                  [[c.replace('_', ' ').title(), score['components'][c], d['weights'][c]] for c in d['weights']],
                                  numeric=[1, 2], note=score['notes'] or None))
        sections += [
            table('By model', ['Model', 'Created', 'Updated', 'Deleted', 'Viewed', 'Field edits', 'Meaningful', 'Automated'],
                  [[m['label'], m['created'], m['updated'], m['deleted'], m['viewed'], m['field_edits'], m['meaningful'], m['automated']]
                   for m in d['by_model']], numeric=range(1, 8)),
            table('Time viewing records (estimate)', ['Model', 'Record', 'Minutes', 'Visits'],
                  [[r['model'], r['record'], r['minutes'], r['visits']] for r in d['top_records']], numeric=[2, 3]),
            table('Recent activity', ['When (UTC)', 'Model', 'Record', 'Operation', 'Origin', 'Fields'],
                  [[a['when'], a['model'], a['record'], a['operation'], a['source'] + (' / automated' if a['automated'] else ''), a['changes']]
                   for a in d['activity']], numeric=[5]),
            table('Recent field changes', ['When (UTC)', 'Model', 'Record', 'Field', 'Was', 'Became'],
                  [[c['when'], c['model'], c['record'], c['field'], c['old'] or '\u2014', c['new'] or '\u2014'] for c in d['changes']]),
        ]
        return {'subtitle': 'Score, activity, field changes and time on records.', 'kpis': kpis, 'sections': sections}

    @api.model
    def _build_fields(self, p):
        d = self.D.get_field_adoption(p['model_name'], p['date_from'], p['date_to'], p['user_id'])
        sections = [
            table('Fields edited', ['Model', 'Field', 'Category', 'Meaningful', 'Edits', 'Users', 'Coverage %', 'Last changed (UTC)'],
                  [[r['model_label'], r['label'], r['category'], 'yes' if r['meaningful'] else '', r['edits'], r['users'], r['coverage'],
                    r['last_changed'] or '\u2014'] for r in d['rows']], numeric=[4, 5, 6]),
            table('Configured but never edited (observed for the whole range)', ['Model', 'Field', 'Meaningful'],
                  [[r['model_label'], r['label'], 'yes' if r['meaningful'] else ''] for r in d['unused']]),
            table('Unknown (not enough history to say)', ['Model', 'Field', 'Why'],
                  [[r['model_label'], r['label'], r['status'].replace('_', ' ')] for r in d['unknown']]),
        ]
        return {'subtitle': 'Which fields are actually maintained: %s.' % d['label'],
                'kpis': [('Model', d['label']), ('Users in scope', d['population']), ('Fields edited', len(d['rows']))],
                'sections': sections, 'notes': d['warnings']}

    @api.model
    def _build_navigation(self, p):
        d = self.D.get_navigation(limit=100, **self._kw(p, 'date_from', 'date_to', 'user_id', 'model_name'))
        k = d['kpis']
        return {'subtitle': 'Browser telemetry: screens opened, not proof of reading.', 'kpis': [
            ('Screens opened', ru.fmt_num(k['total'])), ('Records viewed', k['records']), ('Reports / dashboards', '%s / %s' % (k['reports'], k['dashboards'])),
            ('Searches', k['searches']), ('Attempted actions', k['attempts']), ('Browser sessions', k['sessions']), ('Users', k['users'])],
            'sections': [
                bars('Top pages', [(i['label'], i['value']) for i in d['top_pages']]),
                bars('Most visited models', [(i['label'], i['value']) for i in d['top_models']]),
                table('By user', ['User', 'Screens', 'Pages / lists', 'Records', 'Reports / dashboards', 'Searches'],
                      [[u['name'], u['events'], u['pages'], u['records'], u['reports'], u['searches']] for u in d['by_user']], numeric=range(1, 6)),
                table('Recent navigation', ['When (UTC)', 'User', 'Type', 'Model', 'Record', 'Page'],
                      [[e['when'], e['user'], e['type'].replace('_', ' '), e['model'], e['record'], e['page'] or e['action']] for e in d['events']]),
            ]}

    @api.model
    def _build_activity(self, p):
        d = self.D.get_activity_log(limit=500, export=True, **self._kw(p, 'date_from', 'date_to', 'user_id', 'model_name'))
        return {'subtitle': 'Every successful create, update and delete (first %s of %s shown).' % (len(d['rows']), d['total']),
                'kpis': [('Created', d['counts']['create']), ('Updated', d['counts']['update']), ('Deleted', d['counts']['delete']),
                         ('User-initiated', d['origin']['human']), ('Automated', d['origin']['automated'])],
                'sections': [table('Activity', ['When (UTC)', 'User', 'Model', 'Record', 'Operation', 'Origin', 'Fields', 'Points'],
                                   [[r['when'], r['user'], r['model'], r['record'], r['operation'],
                                     r['source'] + (' / follow-on' if r['type'] == 'secondary' else '') + (' / automated' if r['automated'] else ''),
                                     r['changes'], r['points']] for r in d['rows']], numeric=[6, 7])]}

    @api.model
    def _build_models(self, p):
        d = self.D.get_model_analytics(**self._kw(p, 'date_from', 'date_to', 'user_id', 'model_name'))
        rows = [dict(r, events=r['created'] + r['updated'] + r['deleted']) for r in d['rows']]
        rows = sorted((r for r in rows if r['events'] or r['status'] == 'active'), key=lambda r: -r['events'])
        top = max([r['events'] for r in rows] or [0])
        sections = [
            bars('Model adoption comparison (share of the busiest model)',
                 [(r['label'], ru.share_of_top(r['events'], top)) for r in rows], '%'),
            table('Models', ['Model', 'Status', 'Users', 'Created', 'Updated', 'Deleted', 'Viewed', 'Field edits', 'Time on records (min)'],
                  [[r['label'], r['status'], r['users'], r['created'], r['updated'], r['deleted'], r['viewed'], r['field_edits'], r['minutes']] for r in rows],
                  numeric=range(2, 9)),
        ]
        if d['detail']:
            m = d['detail']
            sections += [
                table('%s: top users' % m['label'], ['User', 'Created', 'Updated', 'Deleted', 'Field edits'],
                      [[u['name'], u['created'], u['updated'], u['deleted'], u['field_edits']] for u in m['top_users']], numeric=range(1, 5)),
                table('%s: most maintained fields' % m['label'], ['Field', 'Edits', 'Coverage %'],
                      [[f['label'], f['edits'], f['coverage']] for f in m['fields']['most']], numeric=[1, 2]),
                table('%s: least maintained fields' % m['label'], ['Field', 'Edits', 'Coverage %'],
                      [[f['label'], f['edits'], f['coverage']] for f in m['fields']['least']], numeric=[1, 2]),
                table('%s: time on records (estimate)' % m['label'], ['Record', 'Minutes', 'Visits'],
                      [[r['record'], r['minutes'], r['visits']] for r in m['time_on_records']], numeric=[1, 2]),
            ]
        return {'subtitle': 'How each Odoo model is created, updated and maintained.',
                'kpis': [('Models compared', len(rows)), ('Created', sum(r['created'] for r in rows)),
                         ('Updated', sum(r['updated'] for r in rows)), ('Deleted', sum(r['deleted'] for r in rows))],
                'sections': sections}

    @api.model
    def _build_reports(self, p):
        s = self.D.get_summary_report(granularity=p['granularity'], **self._kw(p, 'date_from', 'date_to', 'user_id', 'model_name'))
        active = [dict(r, touched=r['created'] + r['updated']) for r in s['rows']
                  if r['events'] + r['field_edits'] + r['viewed'] + r['pages'] + r['reports'] + r['dashboards'] + r['active_minutes'] + r['logins'] > 0]
        compare = ru.comparison_rows(active, 'field_edits')
        kind = {'day': 'Day-over-Day', 'week': 'Week-over-Week', 'month': 'Month-over-Month'}[s['granularity']]
        changes = self.D.get_field_change_report(limit=1, **self._kw(p, 'date_from', 'date_to', 'user_id', 'model_name'))
        t = s['totals']
        return {'subtitle': '%s comparison, grouped by %s.' % (kind, s['granularity']),
                'kpis': [('Created', t['created']), ('Updated', t['updated']), ('Deleted', t['deleted']),
                         ('Field edits', t['field_edits']), ('Active users', t['active_users']), ('Active time', '%s min' % ru.fmt_num(t['active_minutes']))],
                'sections': [
                    bars('%s Comparison \u2014 Field Edits' % kind, [(r['label'], r['field_edits']) for r in active]),
                    table('Comparison table', ['Period', 'Field edits', 'Records touched', 'Active users', 'Change vs previous'],
                          [[r['label'], r['field_edits'], r['touched'], r['active_users'], r['change']] for r in compare], numeric=[1, 2, 3]),
                    table('Detailed summary', ['Period', 'Active users', 'Created', 'Updated', 'Deleted', 'Viewed', 'Field edits', 'Meaningful', 'Active min', 'Logins'],
                          [[r['label'], r['active_users'], r['created'], r['updated'], r['deleted'], r['viewed'], r['field_edits'],
                            r['meaningful'], ru.fmt_num(r['active_minutes']), r['logins']] for r in active], numeric=range(1, 10)),
                    table('Most changed fields', ['Model', 'Field', 'Changes', 'Users', 'Last change (UTC)'],
                          [[f['model'], f['field'], f['edits'], f['users'], f['last'] or '\u2014'] for f in changes['summary']], numeric=[2, 3]),
                ]}
