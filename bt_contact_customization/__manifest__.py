{
    'name': 'Contact Customization',
    'version': '19.0.1.0.0',
    'category': 'Contacts',
    'summary': 'Contact Customization',
    'author': 'Broadtech',
    'depends': ['base', 'contacts', 'utm', 'mail', 'crm'],
    'external_dependencies': {'python': ['openpyxl']},
    'data': [
        'security/ir.model.access.csv',
        'views/res_partner_views.xml',
        'views/contact_account_status.xml',
        'wizard/contact_upload_wizard_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
