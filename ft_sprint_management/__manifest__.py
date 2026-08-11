{
    'name': 'Sprint Management',
    'version': '19.0.1.0.0',
    'category': 'Project',
    'summary': 'Sprint planning for project tasks (list, kanban & form views)',
    'description': """
Sprint Management
=================
Standalone sprint planning for the Project app (extracted from qa_testapp,
behaviour unchanged):
 * Sprint with project, start/end dates and a Planned/Working/Testing/Completed status.
 * Tasks linked to a sprint (Sprint field on the task form).
 * List, Kanban (grouped by status) and Form views, plus a "Sprints" menu under Project.
""",
    'author': 'Fingertip',
    'website': '',
    'depends': ['project'],
    'data': [
        'security/ir.model.access.csv',
        'data/task_stages.xml',
        'views/sprint_views.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
