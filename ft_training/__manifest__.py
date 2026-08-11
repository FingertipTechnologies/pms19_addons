{
    'name': 'Training',
    # 18.0.1.2.0 adds the review period end day, so a review covers a range
    # of days rather than a single one.
    # 18.0.1.2.1 rebalances the Review list's column widths, which that extra
    # column had pushed past the table width — taking Description off screen.
    'version': '19.0.1.2.1',
    'category': 'Human Resources',
    'summary': 'Track daily trainee learning and a central training curriculum',
    'description': """
Training
========
A standalone app to track trainee learning:
 * Learning Trails — central curriculum of Learning Topics (Title, Domain, Description),
   maintained by Admins.
 * Today's Learning — daily learning entries created by Trainees (Learning Topic +
   rich-text Description). Uses the system Created Date, no manual date entry.

Supports evaluating trainee progress from a centralized record.
""",
    'author': 'Fingertip',
    'website': '',
    'depends': ['base', 'web', 'hr'],
    'data': [
        'security/training_security.xml',
        'security/ir.model.access.csv',
        'data/phase_data.xml',
        'views/learning_topic_views.xml',
        'views/today_learning_views.xml',
        'views/trainee_review_views.xml',
        'views/assignment_views.xml',
        'views/evaluation_views.xml',
        'views/phase_views.xml',
        'views/training_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ft_training/static/src/css/training_lists.css',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
