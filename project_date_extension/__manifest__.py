# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Project Milestone Date Extension",
    # 19.0.1.4.0 moves the Date Extensions menu from 60 (which is Test Plans'
    # sequence, dropping it among the QA menus) to 98, beside Change Request
    # at the end of the PMS bar.
    # 19.0.1.5.0 gives the Reason box on a Date Extension Request the width of
    # the form and eight rows of height. It is the case FOR the extension and
    # the only thing an approver reads before deciding, and it was rendering in
    # the 150px LABEL column of its group — an inner group spans two grid
    # columns and a field marked nolabel is not bumped across both, so the
    # reason wrapped after three words. View change only, no migration.
    "version": "19.0.1.5.0",
    "category": "Project",
    "summary": "Approval workflow to request and control milestone date extensions on Projects",
    "description": """
Project Milestone Date Extension
=================================
- Raise a Date Extension Request against a Project and one of its milestones.
- Captures the project, affected milestone, current date, requested new date,
  reason, requester and status.
- Draft -> Approved / Rejected approval workflow.
- Only users in the "Date Extension Approver" security group can approve or
  reject requests.
- Once approved, the milestone date on the Project (project.custom.milestone
  due_date) is updated automatically. Any logic that reads that field will
  then use the revised date. NOTE: in the current PMS, overdue calculations,
  timesheet restrictions and stage validations are driven by the project.task
  deadline / stage flags, NOT by the milestone due_date - so honouring the
  revised date in those places requires wiring the consuming module to read
  this field (see README / point 6 in the spec).
- Full history of every request (old date / new date / who / when) is kept;
  processed requests can never be deleted.
- Smart button on the Project form listing all Date Extension Requests for
  that project.
- Direct edition of a milestone's date is blocked for regular users; only
  members of the approver group may change it directly. Everyone else must
  go through the extension approval process.
- Timesheet validation uses the extended date: while an approved extension
  is in force the milestone/stage cut-off moves to the new date, so entries
  are accepted up to it and refused only beyond it.
""",
    "author": "Custom Development",
    "website": "https://example.com",
    "license": "AGPL-3",
    "depends": ["project_custom_milestone", "hr_timesheet", "mail"],
    "data": [
        "security/project_date_extension_security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "data/project_lifecycle_date_data.xml",
        "views/project_date_extension_views.xml",
        "views/project_project_views.xml",
        "views/project_milestone_views.xml",
        "views/project_task_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
