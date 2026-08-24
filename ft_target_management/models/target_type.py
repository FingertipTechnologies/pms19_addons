from odoo import fields, models


class FtTargetType(models.Model):
    _name = "ft.target.type"
    _description = "KRA"
    _order = "name"

    name = fields.Char(string="KRA Name", required=True)
    department_id = fields.Many2one("hr.department", string="Department")
    job_role_id = fields.Many2one("hr.job", string="Job Role")
    active = fields.Boolean(default=True)
