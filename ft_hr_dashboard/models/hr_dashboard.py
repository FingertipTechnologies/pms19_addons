from odoo import _, api, models
from odoo.exceptions import AccessError

PALETTE = [
    '#4F46E5', '#06B6D4', '#10B981', '#F59E0B', '#EF4444',
    '#8B5CF6', '#EC4899', '#14B8A6', '#F97316', '#3B82F6',
]


class FtHrDashboard(models.TransientModel):
    _name = 'ft.hr.dashboard'
    _description = 'HR Dashboard data provider'

    def _created(self, date_from, date_to, field='create_date'):
        dom = []
        if date_from:
            dom.append((field, '>=', date_from + ' 00:00:00'))
        if date_to:
            dom.append((field, '<=', date_to + ' 23:59:59'))
        return dom

    @api.model
    def _check_hr_dashboard_access(self):
        """Restrict the dashboard to Administrators and HR.

        Hiding the menu is not enough: get_dashboard_data is @api.model, so any
        logged-in user could call it over RPC regardless of what they can see.
        The queries below run sudo(), so without this gate the HR figures would
        be readable by anyone. Kept in step with the groups= on the menu in
        views/hr_dashboard_views.xml.
        """
        if self.env.su:
            return
        user = self.env.user
        if user.has_group('base.group_system') or user.has_group('hr.group_hr_user'):
            return
        raise AccessError(
            _("The HR Dashboard is available to Administrators and HR only.")
        )

    @api.model
    def get_dashboard_data(self, date_from=None, date_to=None):
        self._check_hr_dashboard_access()
        Candidate = self.env['recruitment.candidate'].sudo()
        Interview = self.env['recruitment.interview'].sudo()
        Position = self.env['recruitment.job.position'].sudo()
        Asset = self.env['company.asset'].sudo()

        created = self._created(date_from, date_to)
        iv_dom = self._created(date_from, date_to, field='interview_date')

        # Positions open = total openings on positions in status 'open'
        positions_open = sum(
            g['number_of_openings'] for g in Position.read_group(
                [('status', '=', 'open')], ['number_of_openings:sum'], [])
            if g.get('number_of_openings'))

        applications = Candidate.search_count(created)
        interviews = Interview.search_count(iv_dom)
        hirings = Candidate.search_count([('candidate_status', '=', 'joined')] + created)

        # Laptops = assets whose category name contains "laptop"
        laptops = Asset.search_count([('category.category_name', 'ilike', 'laptop')])

        return {
            'kpis': {
                'positions_open': positions_open,
                'applications': applications,
                'interviews': interviews,
                'hirings': hirings,
                'laptops': laptops,
                # No appraisal module installed → Review is a placeholder.
                'review': None,
            },
            'charts': {
                'candidates_by_status': self._chart_candidates_by_status(created),
                'interviews_by_status': self._chart_interviews_by_status(iv_dom),
            },
        }

    def _chart_candidates_by_status(self, created):
        # sudo() to match get_dashboard_data: the KPI queries above already run
        # sudo, so without it here any user lacking Recruitment User/Manager
        # gets an access error on recruitment.candidate.
        Candidate = self.env['recruitment.candidate'].sudo()
        sel = dict(Candidate.fields_get(['candidate_status'])['candidate_status']['selection'])
        groups = Candidate.read_group(created, [], ['candidate_status'], lazy=False)
        labels = [sel.get(g.get('candidate_status'), g.get('candidate_status') or 'Undefined') for g in groups]
        counts = [g['__count'] for g in groups]
        return {
            'labels': labels,
            'datasets': [{
                'label': 'Candidates',
                'data': counts,
                'backgroundColor': PALETTE[:len(counts)] or ['#4F46E5'],
            }],
        }

    def _chart_interviews_by_status(self, iv_dom):
        # sudo() for the same reason as _chart_candidates_by_status above.
        Interview = self.env['recruitment.interview'].sudo()
        sel = dict(Interview.fields_get(['status'])['status']['selection'])
        groups = Interview.read_group(iv_dom, [], ['status'], lazy=False)
        labels = [sel.get(g.get('status'), g.get('status') or 'Undefined') for g in groups]
        counts = [g['__count'] for g in groups]
        return {
            'labels': labels,
            'datasets': [{
                'data': counts,
                'backgroundColor': PALETTE[:len(counts)] or ['#4F46E5'],
            }],
        }
