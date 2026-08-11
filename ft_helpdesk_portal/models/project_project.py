from odoo import api, models, fields


class ProjectProject(models.Model):
    """Adds compatibility fields for ir.rules that reference removed field names.

    Odoo 18 renamed/removed certain fields on project.project that older
    ir.rule records in the database may still reference.  Adding them back as
    computed/related fields lets the expression engine resolve the domain
    without requiring a database-level migration of those rules.

    - customer_id: renamed to partner_id in Odoo 18.
    - portal_visible: replaced by privacy_visibility == 'portal' in Odoo 18.
    """

    _inherit = 'project.project'

    customer_id = fields.Many2one(
        'res.partner',
        related='partner_id',
        string='Customer',
        store=True,
    )

    portal_visible = fields.Boolean(
        string='Visible on Portal',
        compute='_compute_portal_visible',
        store=True,
    )

    @api.depends('privacy_visibility')
    def _compute_portal_visible(self):
        for project in self:
            project.portal_visible = project.privacy_visibility == 'portal'


class ProjectTask(models.Model):
    """Adds portal_visible compatibility field on project.task.

    ir.rule records in the database may reference portal_visible on
    project.task.  This computed field mirrors the value from the parent
    project so that the expression engine can resolve domain leaves that
    use ('portal_visible', '=', True).
    """

    _inherit = 'project.task'

    portal_visible = fields.Boolean(
        string='Visible on Portal',
        related='project_id.portal_visible',
        store=True,
    )
