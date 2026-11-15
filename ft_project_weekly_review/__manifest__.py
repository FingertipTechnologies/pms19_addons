{
    'name': 'Project Weekly Review',
    # 19.0.1.0.0 first release:
    #   - ft.project.weekly.review: one review per project per ISO week
    #     (unique on project + week_start). Previous weeks are kept.
    #   - "Review" tab on the project form listing the reviews, newest
    #     week first. Only Technical Architect and Delivery Head may
    #     create / edit / delete; everybody else is read-only.
    #   - Delivery Head group (ft_project_weekly_review.group_delivery_head)
    #     under the Project privilege, beside Technical Architect.
    # 19.0.1.1.0: "Review" entry in the Project top menu listing the reviews
    #     of all projects (same rights as the tab).
    # 19.0.1.2.0: Challenges is mandatory (also rejects an empty editor).
    # 19.0.1.2.1: Challenges gets a label and an outlined editor that turns
    #   red when the save is refused for it being empty.
    'version': '19.0.1.2.1',
    'summary': 'Weekly project review (challenges) per ISO week, '
               'editable by Technical Architect and Delivery Head.',
    'category': 'Project',
    'author': 'Fingertip',
    'license': 'LGPL-3',
    'depends': [
        'project',
        'ft_project_stage_dates',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/project_weekly_review_views.xml',
        'views/project_project_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ft_project_weekly_review/static/src/scss/review.scss',
        ],
    },
    'installable': True,
    'application': False,
}
