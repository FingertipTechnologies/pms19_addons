# -*- coding: utf-8 -*-
from odoo import fields, models


class RecruitmentSkill(models.Model):
    _name = "recruitment.skill"
    _description = "Recruitment Skill Tag"
    _order = "name"
    _rec_name = "name"

    name = fields.Char(string="Skill", required=True)
    color = fields.Integer(string="Color")
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint(
        "unique(name)",
        "Skill must be unique.",
    )