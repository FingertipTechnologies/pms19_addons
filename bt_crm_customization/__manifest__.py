{
    'name': 'CRM Customization',
    # 19.0.1.3.8 adds Notes as a column in the Leads list.
    'version': '19.0.1.3.8',
    'category': 'Contacts',
    'summary': 'Contact Customization',
    'author': 'Broadtech',
    # bt_contact_customization brings the account fields (Annual Revenue,
    # Employee Count, Legal Name) that the opportunity fetches and validates.
    # marketing_content provides the Marketing app root menu that Campaigns now
    # hangs off; Project_Scorecards provides the Marketing team group used by
    # the Campaign menu and access rules.
    'depends': [
        'base', 'crm', 'sale_crm',
        'bt_contact_customization',
        'marketing_content',
        'Project_Scorecards',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/crm_lead_views.xml',
        'views/features_views.xml',
        'views/technology_views.xml',
        'views/campaign_views.xml',
        'views/crm_menu_overrides.xml',
        'views/marketing_lead_menu.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'bt_crm_customization/static/src/css/crm_lead.css',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
