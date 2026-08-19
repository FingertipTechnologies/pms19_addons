{
    'name': 'CRM Team Dashboard (v18 card)',
    'version': '19.0.1.0.0',
    'category': 'Sales/CRM',
    'summary': 'Restores the Odoo 18 sales team dashboard card removed in Odoo 19',
    'description': """
Odoo 19 stripped the Sales Team kanban card down to the team name, email alias,
unassigned lead count and the salesperson avatar. The counts, the amounts, the
weekly bar chart and the invoicing target that Odoo 18 showed were removed both
from the views and from the ``crm.team`` model.

This module puts them back:

* ``opportunities_count`` / ``opportunities_amount``
* ``opportunities_overdue_count`` / ``opportunities_overdue_amount``
* ``quotations_count`` / ``quotations_amount`` / ``sales_to_invoice_count``
* ``dashboard_graph_data`` feeding the ``dashboard_graph`` widget still shipped
  by ``web``

The Pipeline button, the invoicing-target progress bar (``sales_team_progressbar``,
still shipped by ``sale``) and the dropdown entries all come back with them.
    """,
    'author': 'Fingertip Technologies',
    'website': 'https://www.fingertipplus.com',
    'depends': ['crm', 'sale'],
    'data': [
        'views/crm_team_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ft_crm_team_dashboard/static/src/scss/crm_team_dashboard.scss',
        ],
    },
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
}
