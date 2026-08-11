{
    "name": "Scorecard",
    "version": "19.0.1.0",
    "category": "Project",
    "summary": "Project Scorecard for tracking meetings and hours",
    "depends": ["project","bt_project_customization"],
    "data": [
        "security/scorecard_security.xml",
        "security/ir.model.access.csv",
        "views/project_scorecard_views.xml",
        "views/sales_scorecard_views.xml",
        "views/marketing_scorecard_views.xml",
        "views/hr_recruitment_scorecard_views.xml",
        "views/hr_training_scorecard_views.xml",
        "views/hr_team_activity_views.xml",
        "views/hr_policy_views.xml",
        "views/finance_scorecard_views.xml"

    ],
    'assets': {
        'web.assets_backend': [
            'Project_Scorecards/static/src/js/many2many_binary_preview.js',
            'Project_Scorecards/static/src/xml/many2many_binary_preview.xml',
        ],
    },
    'images': ['static/description/icon.png'],
    "installable": True,
    "application": True,
}
