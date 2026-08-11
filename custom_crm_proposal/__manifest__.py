{
    'name': 'CRM Proposal Management',
    'version': '19.0.1.0',
    'category': 'Sales',
    'depends': ['crm', 'sale_crm'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'views/crm_proposal_report.xml',
        'views/crm_proposal_views.xml',
        'views/crm_lead_views.xml',
        
    ],
    'installable': True,
    'application': False,
}