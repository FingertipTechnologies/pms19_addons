from odoo import fields, models


class ModuleModule(models.Model):
    _name = 'cus.module'
    _description = 'Project Module'

    name = fields.Char(string="Status Name", required=True)
    description = fields.Text(string="Description")
    task_ids = fields.One2many('project.task', 'module_id', string='Tasks')
    complete_date = fields.Date(string="Completion Date")
    # The modules a project offers are CONFIGURED here (or from the project's
    # own Modules tab, which is the same relation seen from the other side), and
    # this is what the Module field on a task is filtered against.
    #
    # This used to be computed from task_ids.project_id, which made it useless
    # as a filter: a module only appeared under a project once a task had
    # already been given that pairing, so the field could only ever describe
    # choices that had been made, never constrain the next one. The relation
    # table and its columns are pinned so that switching the field from computed
    # to editable REUSES the rows the compute had already written — every
    # project therefore starts out configured with exactly the modules its tasks
    # were using, and nothing has to be re-entered by hand.
    project_ids = fields.Many2many(
        'project.project',
        relation='cus_module_project_project_rel',
        column1='cus_module_id',
        column2='project_project_id',
        string='Projects',
        help='Projects that offer this module. A task can only be given a '
             'module that its project lists here.',
    )
