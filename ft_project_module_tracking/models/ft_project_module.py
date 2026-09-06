# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

class ProjectProject(models.Model):
    _inherit = 'project.project'

    # Requirement #1/#2 -- the modules configured under this project.
    ft_module_ids = fields.One2many(
        'ft.project.module', 'project_id', string='Project Modules')

    ft_stagewise_time_ids = fields.One2many(
        'ft.stagewise.time', 'project_id',
        string='Stage-wise Time', readonly=True)

class FtProjectModule(models.Model):
    """A functional module assigned to ONE specific project.

    Top-level rows reference an Odoo application (ir.module.module,
    application=True). Sub-module rows reference a non-application module
    and link back to the parent app via parent_module_ref_id. No self-
    referencing tree, no recursion risk.
    """
    _name = 'ft.project.module'
    _description = 'Project Module'
    _order = 'project_id, sequence, name'
    _rec_name = 'display_name_stored'

    # --- The Odoo module this row represents ---
    module_ref_id = fields.Many2one(
        'ir.module.module', string='Application',
        ondelete='cascade', index=True)

    # For a sub-module row: which parent APPLICATION it belongs under.
    # Empty on top-level (application) rows.
    parent_module_ref_id = fields.Many2one(
        'ir.module.module', string='Parent Application',
        ondelete='cascade', index=True)

    is_submodule = fields.Boolean(
        string='Is Sub-Module', compute='_compute_is_submodule', store=True)

    category_id = fields.Many2one(
        'ir.module.category', string='Category',
        related='module_ref_id.category_id', store=True)

    name = fields.Char(string='Module', required=True)
    code = fields.Char(
        string='Technical Name', related='module_ref_id.name', store=True)
    display_name_stored = fields.Char(
        string='Display Name', compute='_compute_display_name_stored', store=True)

    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    project_id = fields.Many2one(
        'project.project', string='Project',
        required=True, ondelete='cascade', index=True)

    _sql_constraints = [
        ('uniq_project_module',
         'unique(project_id, module_ref_id, parent_module_ref_id)',
         'This module is already listed for the project.'),
    ]

    @api.depends('parent_module_ref_id')
    def _compute_is_submodule(self):
        for rec in self:
            rec.is_submodule = bool(rec.parent_module_ref_id)

    @api.depends('name', 'parent_module_ref_id')
    def _compute_display_name_stored(self):
        for rec in self:
            if rec.parent_module_ref_id:
                parent_name = (rec.parent_module_ref_id.sudo().shortdesc
                               or rec.parent_module_ref_id.name or '')
                rec.display_name_stored = '%s / %s' % (parent_name, rec.name or '')
            else:
                rec.display_name_stored = rec.name or ''

    # ------------------------------------------------------------------ #
    # When an application is picked on a top-level row, set the name.
    # Sub-modules are NOT auto-filled here — the user adds them from a
    # category-filtered dropdown in the project form.
    # ------------------------------------------------------------------ #
    @api.onchange('module_ref_id')
    def _onchange_module_ref_id(self):
        if not self.module_ref_id:
            return
        app = self.module_ref_id.sudo()
        self.name = app.shortdesc or app.name or ''
