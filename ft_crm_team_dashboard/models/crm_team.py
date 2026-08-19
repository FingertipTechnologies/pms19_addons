"""Restore the Odoo 18 sales team dashboard card.

Odoo 19 removed the count/amount fields and the whole graph framework from
``crm.team`` (``sales_team``, ``crm`` and ``sale`` all dropped their share of
it). The widgets that rendered them - ``dashboard_graph`` in ``web`` and
``sales_team_progressbar`` in ``sale`` - are still shipped, so only the data
side has to be rebuilt here.

The v18 implementation used raw SQL through ``_where_calc`` / ``_apply_ir_rules``;
neither exists in v19, so the aggregations are done with ``_read_group``, which
applies record rules on its own and keeps this module free of hand-written SQL.
"""

import json

from datetime import date

from babel.dates import format_date
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models


class CrmTeam(models.Model):
    _inherit = 'crm.team'

    # --- pipeline (restored from v18 crm/models/crm_team.py) ---
    opportunities_count = fields.Integer(
        string='# Opportunities', compute='_compute_opportunities_data')
    opportunities_amount = fields.Monetary(
        string='Opportunities Revenues', compute='_compute_opportunities_data')
    opportunities_overdue_count = fields.Integer(
        string='# Overdue Opportunities', compute='_compute_opportunities_overdue_data')
    opportunities_overdue_amount = fields.Monetary(
        string='Overdue Opportunities Revenues', compute='_compute_opportunities_overdue_data')

    # --- quotations (restored from v18 sale/models/crm_team.py) ---
    quotations_count = fields.Integer(
        string='Number of quotations to invoice',
        compute='_compute_quotations_to_invoice')
    quotations_amount = fields.Monetary(
        string='Amount of quotations to invoice',
        compute='_compute_quotations_to_invoice')
    sales_to_invoice_count = fields.Integer(
        string='Number of sales to invoice', compute='_compute_sales_to_invoice')

    # --- graph (restored from v18 sales_team/models/crm_team.py) ---
    dashboard_graph_data = fields.Text(compute='_compute_dashboard_graph')

    # ------------------------------------------------------------
    # COMPUTE
    # ------------------------------------------------------------

    def _compute_opportunities_data(self):
        opportunity_data = self.env['crm.lead']._read_group([
            ('team_id', 'in', self.ids),
            ('probability', '<', 100),
            ('type', '=', 'opportunity'),
        ], ['team_id'], ['__count', 'expected_revenue:sum'])
        counts_amounts = {
            team.id: (count, expected_revenue_sum)
            for team, count, expected_revenue_sum in opportunity_data
        }
        for team in self:
            team.opportunities_count, team.opportunities_amount = counts_amounts.get(team.id, (0, 0))

    def _compute_opportunities_overdue_data(self):
        opportunity_data = self.env['crm.lead']._read_group([
            ('team_id', 'in', self.ids),
            ('probability', '<', 100),
            ('type', '=', 'opportunity'),
            ('date_deadline', '<', fields.Date.context_today(self)),
        ], ['team_id'], ['__count', 'expected_revenue:sum'])
        counts_amounts = {
            team.id: (count, expected_revenue_sum)
            for team, count, expected_revenue_sum in opportunity_data
        }
        for team in self:
            team.opportunities_overdue_count, team.opportunities_overdue_amount = \
                counts_amounts.get(team.id, (0, 0))

    def _compute_quotations_to_invoice(self):
        # grouped by currency as well: orders may be in any currency, while the
        # card shows the amount in the team's (company) currency
        quotation_data = self.env['sale.order']._read_group([
            ('team_id', 'in', self.ids),
            ('state', 'in', ['draft', 'sent']),
        ], ['team_id', 'currency_id'], ['__count', 'amount_total:sum'])
        counts = dict.fromkeys(self.ids, 0)
        amounts = dict.fromkeys(self.ids, 0.0)
        today = fields.Date.context_today(self)
        for team, currency, count, amount_total in quotation_data:
            counts[team.id] += count
            company = team.company_id or self.env.company
            amounts[team.id] += currency._convert(
                amount_total, team.currency_id or company.currency_id, company, today,
            )
        for team in self:
            team.quotations_count = counts.get(team.id, 0)
            team.quotations_amount = amounts.get(team.id, 0.0)

    def _compute_sales_to_invoice(self):
        sale_order_data = self.env['sale.order']._read_group([
            ('team_id', 'in', self.ids),
            ('invoice_status', '=', 'to invoice'),
        ], ['team_id'], ['__count'])
        data_map = {team.id: count for team, count in sale_order_data}
        for team in self:
            team.sales_to_invoice_count = data_map.get(team.id, 0)

    @api.depends_context('in_sales_app', 'lang')
    def _compute_dashboard_graph(self):
        for team in self:
            team.dashboard_graph_data = json.dumps(team._get_dashboard_graph_data())

    # ------------------------------------------------------------
    # GRAPH
    # ------------------------------------------------------------

    def _in_sale_scope(self):
        """The Sales app passes ``in_sales_app``; CRM does not. Same switch v18 used
        to decide between an invoiced-amount graph and a new-opportunities graph."""
        return self.env.context.get('in_sales_app')

    def _graph_get_dates(self, today):
        """Start/end covering roughly a month, aligned on the start of a week so
        the same week never shows up twice."""
        start_date = today - relativedelta(months=1)
        start_date += relativedelta(days=8 - start_date.isocalendar()[2])
        return [start_date, today]

    def _graph_week_label(self, start_date, locale):
        """'16-22 Nov', or '28 Dec-3 Jan' when the week straddles two months."""
        end_date = start_date + relativedelta(days=6)
        if end_date.month == start_date.month:
            short_name_from = format_date(start_date, 'd', locale=locale)
        else:
            short_name_from = format_date(start_date, 'd MMM', locale=locale)
        return f"{short_name_from}-{format_date(end_date, 'd MMM', locale=locale)}"

    def _graph_read_group(self, start_date, end_date):
        """Return {monday of the week: value} for this team.

        Grouping is done per day and bucketed into ISO (Monday-based) weeks in
        Python on purpose: v19's ``:week`` granularity truncates on the *lang's*
        first day of week - Sunday for en_US - while the v18 card labelled its
        bars Monday-to-Sunday. Bucketing here keeps the bars aligned with their
        labels whatever the language.

        ``_read_group`` applies record rules by itself, which is what the v18
        ``_apply_ir_rules`` call did by hand.
        """
        self.ensure_one()
        if self._in_sale_scope():
            model, date_field, aggregate = 'sale.report', 'date', 'price_subtotal:sum'
            domain = [('state', '=', 'sale')]
        else:
            model, date_field, aggregate = 'crm.lead', 'create_date', '__count'
            domain = [('type', '=', 'opportunity')]
        # amounts must stay in the team's own currency, not the active company's
        Model = self.env[model].with_company(self.company_id or self.env.company)
        rows = Model._read_group(
            domain + [
                ('team_id', '=', self.id),
                (date_field, '>=', fields.Date.to_string(start_date)),
                (date_field, '<=', fields.Date.to_string(end_date + relativedelta(days=1))),
            ],
            [f'{date_field}:day'],
            [aggregate],
        )
        values = {}
        for period_start, value in rows:
            if not period_start:
                continue
            day = period_start.date() if hasattr(period_start, 'date') else period_start
            monday = day - relativedelta(days=day.isocalendar()[2] - 1)
            values[monday] = values.get(monday, 0) + (value or 0)
        return values

    def _graph_title_and_key(self):
        if self._in_sale_scope():
            return ['', self.env._('Sales: Untaxed Total')]
        return ['', self.env._('New Opportunities')]

    def _get_dashboard_graph_data(self):
        self.ensure_one()
        today = fields.Date.from_string(fields.Date.context_today(self))
        start_date, end_date = self._graph_get_dates(today)
        grouped = self._graph_read_group(start_date, end_date)

        locale = self.env.context.get('lang') or 'en_US'
        # weeks are keyed on the Monday, the same day _read_group's 'week'
        # granularity truncates to
        first_monday = start_date - relativedelta(days=start_date.isocalendar()[2] - 1)
        last_monday = today - relativedelta(days=today.isocalendar()[2] - 1)
        week_count = int((last_monday - first_monday).days / 7) + 1

        values = []
        for week in range(week_count):
            monday = first_monday + relativedelta(days=7 * week)
            values.append({
                'label': self._graph_week_label(monday, locale),
                'value': grouped.get(monday, 0),
                'type': 'future' if week + 1 == week_count else 'past',
            })

        graph_title, graph_key = self._graph_title_and_key()
        return [{
            'values': values,
            'area': True,
            'title': graph_title,
            'key': graph_key,
            'color': '#875A7B',
        }]
