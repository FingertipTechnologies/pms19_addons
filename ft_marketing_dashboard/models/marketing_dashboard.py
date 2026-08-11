from odoo import api, models

PALETTE = [
    '#4F46E5', '#06B6D4', '#10B981', '#F59E0B', '#EF4444',
    '#8B5CF6', '#EC4899', '#14B8A6', '#F97316', '#3B82F6',
]


class FtMarketingDashboard(models.TransientModel):
    _name = 'ft.marketing.dashboard'
    _description = 'Marketing Dashboard data provider'

    def _created_domain(self, date_from, date_to):
        dom = []
        if date_from:
            dom.append(('create_date', '>=', date_from + ' 00:00:00'))
        if date_to:
            dom.append(('create_date', '<=', date_to + ' 23:59:59'))
        return dom

    @api.model
    def get_dashboard_data(self, date_from=None, date_to=None):
        Lead = self.env['crm.lead']
        Enquiry = self.env['marketing.enquiry']
        Campaign = self.env['utm.campaign']
        created = self._created_domain(date_from, date_to)

        # Leads = CRM leads (type=lead) + website marketing enquiries
        crm_leads = Lead.search_count([('type', '=', 'lead')] + created)
        enquiries = Enquiry.search_count(created)
        leads_generated = crm_leads + enquiries

        # Active campaigns (snapshot — not date-filtered)
        campaigns = Campaign.search_count([('active', '=', True)])

        return {
            'kpis': {
                'leads_generated': leads_generated,
                'campaigns': campaigns,
                # No spend/revenue data on utm.campaign in this DB → placeholders.
                'campaign_spent': None,
                'campaign_roi': None,
            },
            'charts': {
                'leads_by_source': self._chart_leads_by_source(created),
                'enquiries_by_domain': self._chart_enquiries_by_domain(created),
            },
        }

    def _chart_leads_by_source(self, created):
        groups = self.env['crm.lead'].read_group(
            [('type', '=', 'lead')] + created, [], ['source_id'], lazy=False)
        labels = [g['source_id'][1] if g.get('source_id') else 'Undefined' for g in groups]
        counts = [g['__count'] for g in groups]
        return {
            'labels': labels,
            'datasets': [{
                'label': 'Leads',
                'data': counts,
                'backgroundColor': PALETTE[:len(counts)] or ['#4F46E5'],
            }],
        }

    def _chart_enquiries_by_domain(self, created):
        groups = self.env['marketing.enquiry'].read_group(
            created, [], ['domain'], lazy=False)
        labels = [g.get('domain') or 'Undefined' for g in groups]
        counts = [g['__count'] for g in groups]
        return {
            'labels': labels,
            'datasets': [{
                'data': counts,
                'backgroundColor': PALETTE[:len(counts)] or ['#4F46E5'],
            }],
        }
