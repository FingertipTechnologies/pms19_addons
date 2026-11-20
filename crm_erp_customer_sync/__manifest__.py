{
    "name": "CRM/PMS to ERP Customer Integration",
    "version": "19.0.1.1.0",
    "category": "CRM",
    "summary": "Queue Won companies and new child contacts to ERP every minute",
    "author": "Custom Development",
    "license": "LGPL-3",
    "depends": ["base", "crm", 'mail',"contacts", "bt_contact_customization"],
    "external_dependencies": {
        "python": [
            "requests"
        ]
    },
    "data": [
        "data/cron.xml",
        "data/ir_actions_historical_sync.xml",
        "views/res_partner_views.xml",
        "views/res_config_settings_views.xml"
    ],
    "installable": True,
    "application": True
}
