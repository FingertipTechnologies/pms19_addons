# -*- coding: utf-8 -*-
from odoo import api, fields, models


class RecruitmentJobPosition(models.Model):
    _name = "recruitment.job.position"
    _description = "Recruitment Job Position"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"
    _rec_name = "job_title"

    job_title = fields.Char(string="Job Title", required=True, tracking=True)
    department = fields.Many2one(
        'hr.department', string="Department", required=True, tracking=True)
    hiring_manager = fields.Many2one(
        'hr.employee', string="Hiring Manager", tracking=True)
    number_of_openings = fields.Integer(
        string="Number of Openings", required=True, default=1)
    employment_type = fields.Selection(
        selection=[
            ('full_time', 'Full-time'),
            ('internship', 'Internship'),
            ('contract', 'Contract'),
            ('consultant', 'Consultant'),
        ],
        string="Employment Type", required=True, default='full_time')
    work_location = fields.Char(string="Work Location")
    experience_required = fields.Char(string="Experience Required")

    # Compensation
    salary_range_from = fields.Monetary(string="Salary Range From")
    salary_range_to = fields.Monetary(string="Salary Range To")
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id)

    # Job Details
    job_description = fields.Html(string="Job Description")
    required_skill_ids = fields.Many2many(
        'recruitment.skill',
        'recruitment_job_position_skill_rel',
        'job_position_id', 'skill_id',
        string="Required Skills",
        help="Required skill tags for filtering.")

    # Status
    status = fields.Selection(
        selection=[
            ('open', 'Open'),
            ('on_hold', 'On Hold'),
            ('closed', 'Closed'),
        ],
        string="Status", required=True, default='open', tracking=True)

    # Pipeline counts
    candidate_ids = fields.One2many(
        'recruitment.candidate', 'applied_position',
        string="Candidates")
    candidate_count = fields.Integer(
        compute='_compute_candidate_count', string="Candidate Count")

    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company)
    active = fields.Boolean(default=True)

    @api.depends('candidate_ids')
    def _compute_candidate_count(self):
        for rec in self:
            rec.candidate_count = len(rec.candidate_ids)

    def action_view_candidates(self):
        self.ensure_one()
        return {
            'name': "Candidates",
            'type': 'ir.actions.act_window',
            'res_model': 'recruitment.candidate',
            'view_mode': 'list,form,kanban',
            'domain': [('applied_position', '=', self.id)],
            'context': {'default_applied_position': self.id},
        }