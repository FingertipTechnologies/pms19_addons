from odoo import _, api, models
from odoo.exceptions import UserError


class ProjectTaskType(models.Model):
    _inherit = 'project.task.type'

    @api.model_create_multi
    def create(self, vals_list):
        """Nobody adds a task stage: the PMS runs on Planned, Working, Testing
        and Completed only.

        The Kanban's "Add column" is hidden in the views, but that is only the
        button — the column quick create, a stage many2one's "Create", an import
        and a plain RPC all end up here, so this is where it is enforced.

        Superuser mode is let through, which is what keeps Odoo itself working:
        module data (data/task_stages.xml) loads as superuser, and core creates
        each user's personal My Tasks stages and a project's on-the-fly stage in
        sudo.
        """
        if not self.env.su:
            raise UserError(_(
                "Task stages cannot be added. Tasks use Planned, Working, "
                "Testing and Completed only."
            ))
        return super().create(vals_list)
