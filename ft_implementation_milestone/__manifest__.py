# -*- coding: utf-8 -*-
{
    'name': 'Implementation Payment Milestones',
    # 19.0.1.0.0 first release (requirements 51-56 of the PMS spec):
    #   - Milestone templates (Advance, BRD Approval, delivery milestones) and
    #     an "Apply Template" wizard on the project form's Milestones tab,
    #     offered while an Implementation project is still in KICKOFF / DISC.
    #   - The milestone percentages of an Implementation project must add up
    #     to 100% before every forward stage move (KICKOFF -> DISC first of
    #     all); the Missing-for-Next-Stage checklist lists the shortfall.
    #   - Once the project has left KICKOFF the agreed plan (names,
    #     percentages, amounts, dates) is locked for everybody but the Date
    #     Extension Approvers; changes go through a Milestone Change Request
    #     (draft -> request -> approved / rejected) whose approval applies the
    #     change and must leave the plan at 100%.
    # 19.0.1.1.0: Standard Implementation template = the seven named milestones
    #   (Advance, BRD Approval, After Sandbox Review, Before UAT, After UAT,
    #   Before First User Onboarding, Final Project Handover); a pre-migration
    #   swaps the old placeholder lines (or keeps an edited set on a copy).
    # 19.0.1.2.0: templates are flat. ft.milestone.template IS one milestone
    #   (name, order, delivery stage, description - no percentage, no parent
    #   "Standard Implementation" plan); the Milestone Templates menu lists
    #   the seven milestones directly. A new Implementation project (or one
    #   converted to Implementation) with no milestone of its own receives
    #   every active template at 0% and no due date; the PM enters the
    #   percentages during KICKOFF and the 100% gate applies as before. The
    #   Apply Template wizard is gone (no button: the milestones are simply
    #   there). A pre-migration flattens the existing template lines and
    #   drops the parent records.
    # 19.0.1.3.0: customer e-mail on milestone completion: when a payment
    #   milestone of an Implementation project is marked Completed, the
    #   template "Implementation: Milestone Completed" is queued to the
    #   project's customer (switch on the project's Milestones tab, default
    #   on; AMC monthly milestones keep their own e-mail). Logged on the
    #   project's chatter; a customer without e-mail gets a note instead.
    'version': '19.0.1.4.0',
    'summary': 'Milestone templates added to every new Implementation project '
               'at 0%, the 100% plan gate and the locked plan / change-request '
               'flow.',
    'category': 'Project',
    'author': 'Fingertip',
    'license': 'LGPL-3',
    'depends': [
        'project_custom_milestone',
        'qa_testapp',
        'project_date_extension',
        'ft_pms_planning_workflow',
        'ft_project_stage_dates',
        'bt_project_customization',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/milestone_template_data.xml',
        'data/mail_template_milestone_completed.xml',
        # Wizard action first: the request form references the reject
        # wizard action by xmlid, so it must exist before that view loads.
        'wizard/milestone_change_reject_wizard_views.xml',
        'views/milestone_template_views.xml',
        'views/milestone_change_request_views.xml',
        'views/project_milestone_views.xml',
        'views/project_project_views.xml',
    ],
    'installable': True,
    'application': False,
}
