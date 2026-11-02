{
    'name': 'Project Stage Dates (KICKOFF, actual entry dates, Technical Architect)',
    # 19.0.1.0.0 first release:
    #   - KICKOFF stage (sequence 5, Implementation only) ahead of DISC; new
    #     Implementation projects start in it (ft_project_lifecycle homes a new
    #     project on the lowest-sequence stage of its type). Existing projects
    #     are not moved.
    #   - pl_actual_<key>_date: the date a project first ENTERED each
    #     Implementation stage, stamped automatically on create / stage change
    #     and refused on any direct write (first entry is kept). The
    #     post_init_hook backfills them from the stage_id chatter tracking.
    #   - Technical Architect group: may edit the planned lifecycle dates
    #     directly while an Implementation project is in KICKOFF or DISC; the
    #     Date Extension Approver keeps its rights; everyone else still goes
    #     through the Date Extension Request flow.
    #   - Kick-off Date and Closed Date join project_date_extension's
    #     protected / sequenced set (they were matched by label and never
    #     were), and the five lifecycle dates the form showed as editable are
    #     now read-only unless the user may edit project dates.
    'version': '19.0.1.0.0',
    'summary': 'KICKOFF stage, automatic actual stage-entry dates and the '
               'Technical Architect planning-date rights for Implementation '
               'projects.',
    'category': 'Project',
    'author': 'Fingertip',
    'license': 'LGPL-3',
    'depends': [
        'project',
        'mail',
        'bt_project_customization',
        'ft_task_hours_tracker',
        'ft_project_lifecycle',
        'project_date_extension',
        'ft_pms_planning_workflow',
    ],
    'data': [
        'security/security.xml',
        'data/project_project_stage_data.xml',
        'views/project_project_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
}
