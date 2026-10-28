# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ProjectTaskUserGroup(models.Model):
    _name = 'project.task.user.group'
    _description = 'Task Assignee Group'
    _order = 'name'

    name = fields.Char(string='Group Name', required=True)
    active = fields.Boolean(default=True)
    description = fields.Text(string='Description')
    user_ids = fields.Many2many(
        'res.users',
        'project_task_user_group_res_users_rel',
        'group_id',
        'user_id',
        string='Members',
        required=True,
    )
    user_count = fields.Integer(
        string='Member Count',
        compute='_compute_user_count',
        store=True,
    )

    @api.depends('user_ids')
    def _compute_user_count(self):
        for rec in self:
            rec.user_count = len(rec.user_ids)

    @api.constrains('name')
    def _check_name_unique(self):
        for rec in self:
            if rec.name and self.search_count([('id', '!=', rec.id), ('name', '=ilike', rec.name.strip())]):
                raise ValidationError(_("A user group with the name '%s' already exists.", rec.name))
