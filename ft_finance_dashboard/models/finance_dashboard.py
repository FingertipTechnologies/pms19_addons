from odoo import api, models


class FtFinanceDashboard(models.TransientModel):
    _name = 'ft.finance.dashboard'
    _description = 'Finance Dashboard data provider'

    # ------------------------------------------------------------------
    def _sum(self, model, domain, field):
        return sum(
            g[field] for g in self.env[model].read_group(domain, [f'{field}:sum'], [])
            if g.get(field)
        )

    def _inv_domain(self, move_types, date_from, date_to, extra=None):
        dom = [('state', '=', 'posted'), ('move_type', 'in', move_types)]
        if date_from:
            dom.append(('invoice_date', '>=', date_from))
        if date_to:
            dom.append(('invoice_date', '<=', date_to))
        return dom + (extra or [])

    # ------------------------------------------------------------------
    @api.model
    def get_dashboard_data(self, date_from=None, date_to=None):
        Move = 'account.move'
        Payment = 'account.payment'

        # Revenue = posted customer invoices - credit notes
        revenue = (self._sum(Move, self._inv_domain(['out_invoice'], date_from, date_to), 'amount_total')
                   - self._sum(Move, self._inv_domain(['out_refund'], date_from, date_to), 'amount_total'))

        # Expense = posted vendor bills - refunds
        expense = (self._sum(Move, self._inv_domain(['in_invoice'], date_from, date_to), 'amount_total')
                   - self._sum(Move, self._inv_domain(['in_refund'], date_from, date_to), 'amount_total'))

        # Outstanding = open balance on posted customer invoices (not fully paid)
        outstanding = self._sum(
            Move,
            self._inv_domain(['out_invoice'], date_from, date_to,
                             [('payment_state', 'in', ['not_paid', 'partial'])]),
            'amount_residual')

        # Collection = inbound customer payments in the period
        pay_domain = [
            ('payment_type', '=', 'inbound'),
            ('partner_type', '=', 'customer'),
            ('state', 'not in', ['draft', 'cancel', 'canceled', 'rejected']),
        ]
        if date_from:
            pay_domain.append(('date', '>=', date_from))
        if date_to:
            pay_domain.append(('date', '<=', date_to))
        collection = self._sum(Payment, pay_domain, 'amount')

        return {
            'kpis': {
                'revenue': round(revenue, 2),
                'outstanding': round(outstanding, 2),
                'collection': round(collection, 2),
                'expense': round(expense, 2),
            },
            'charts': {
                'summary': self._chart_summary(revenue, collection, outstanding, expense),
                'trend': self._chart_trend(date_from, date_to),
            },
        }

    # ------------------------------------------------------------------
    def _chart_summary(self, revenue, collection, outstanding, expense):
        return {
            'labels': ['Revenue', 'Collection', 'Outstanding', 'Expense'],
            'datasets': [{
                'label': 'Amount',
                'data': [round(revenue, 2), round(collection, 2),
                         round(outstanding, 2), round(expense, 2)],
                'backgroundColor': ['#10B981', '#4F46E5', '#F59E0B', '#EF4444'],
            }],
        }

    def _chart_trend(self, date_from, date_to):
        """Monthly Revenue vs Expense over the selected range."""
        Move = self.env['account.move']

        def by_month(move_types):
            out = {}
            dom = [('state', '=', 'posted'), ('move_type', 'in', move_types)]
            if date_from:
                dom.append(('invoice_date', '>=', date_from))
            if date_to:
                dom.append(('invoice_date', '<=', date_to))
            for g in Move.read_group(dom, ['amount_total:sum'], ['invoice_date:month'], lazy=False):
                label = g.get('invoice_date:month')
                if label:
                    out[label] = round(g.get('amount_total') or 0.0, 2)
            return out

        rev = by_month(['out_invoice'])
        exp = by_month(['in_invoice'])
        labels = sorted(set(rev) | set(exp))
        return {
            'labels': labels,
            'datasets': [
                {
                    'label': 'Revenue',
                    'data': [rev.get(m, 0) for m in labels],
                    'borderColor': '#10B981', 'backgroundColor': 'rgba(16,185,129,0.15)',
                    'tension': 0.35, 'fill': True,
                },
                {
                    'label': 'Expense',
                    'data': [exp.get(m, 0) for m in labels],
                    'borderColor': '#EF4444', 'backgroundColor': 'rgba(239,68,68,0.15)',
                    'tension': 0.35, 'fill': True,
                },
            ],
        }
