# -*- coding: utf-8 -*-
{
    'name': 'Adoption Intelligence',
    'version': '19.0.1.0.0',
    'category': 'Productivity',
    'summary': 'Measure whether people actually use Odoo: tracked CRUD with old/new values, '
               'engagement, adoption scoring and dashboards. No browser extension.',
    'description': """
Adoption Intelligence (native Odoo 19 port of the Salesforce Adoption Intelligence app)
=======================================================================================
* Server-side CRUD tracking with field-level old/new values, configured from the UI.
* Web-client tracker (no Chrome extension): navigation, record views, active time.
* Nightly rollups, six-component adoption score (p75 normalised), leaderboards.
* Field adoption, health checks, XLSX / PDF exports, retention, security groups.
""",
    'author': 'Adoption Intelligence',
    'license': 'LGPL-3',
    'depends': ['base', 'web'],
    'data': [
        'security/adoption_groups.xml',
        'security/ir.model.access.csv',
        'security/adoption_rules.xml',
        'data/adoption_seed_data.xml',
        'data/adoption_cron.xml',
        'views/adoption_activity_views.xml',
        'views/adoption_field_change_views.xml',
        'views/adoption_summary_views.xml',
        'views/adoption_configuration_views.xml',
        'views/adoption_dashboard_views.xml',
        'views/adoption_menu.xml',
        'report/adoption_report.xml',
        'report/adoption_screen_report.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'adoption_intelligence/static/src/js/**/*',
            'adoption_intelligence/static/src/xml/**/*',
            'adoption_intelligence/static/src/scss/**/*',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'application': True,
    'installable': True,
}
