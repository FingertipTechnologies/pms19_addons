# -*- coding: utf-8 -*-
import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class RecruitmentCandidate(models.Model):
    _name = "recruitment.candidate"
    _description = "Recruitment Candidate"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"
    _rec_name = "candidate_name"

    candidate_name = fields.Char(
        string="Candidate Name", required=True, tracking=True)
    mobile_number = fields.Char(
        string="Mobile Number", required=True, tracking=True)
    email = fields.Char(string="Email", required=True, tracking=True)
    current_location = fields.Char(string="Current Location")
    preferred_location = fields.Char(string="Preferred Location")

    # Experience
    current_company = fields.Char(string="Current Company")
    current_designation = fields.Char(string="Current Designation")
    total_experience = fields.Float(string="Total Experience (Years)")
    relevant_experience = fields.Float(string="Relevant Experience (Years)")

    # Compensation
    current_ctc = fields.Monetary(string="Current CTC")
    expected_ctc = fields.Monetary(string="Expected CTC")
    notice_period = fields.Char(string="Notice Period")
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id)

    # Source
    source = fields.Selection(
        selection=[
            ('linkedin', 'LinkedIn'),
            ('naukri', 'Naukri'),
            ('referral', 'Referral'),
            ('website', 'Website'),
            ('walk_in', 'Walk-in'),
            ('consultant', 'Consultant'),
            ('other', 'Other'),
        ],
        string="Source", tracking=True)
    referred_by = fields.Many2one(
        'hr.employee', string="Referred By")

    # Application
    applied_position = fields.Many2one(
        'recruitment.job.position', string="Applied Position",
        required=True, tracking=True)

    # Documents & Links
    resume_attachment = fields.Many2many(
        'ir.attachment', 'recruitment_candidate_resume_rel',
        'candidate_id', 'attachment_id', string="Resume Attachment")
    linkedin_url = fields.Char(string="LinkedIn URL")
    portfolio_github_url = fields.Char(string="Portfolio / GitHub URL")
    skill_ids = fields.Many2many(
        'recruitment.skill',
        'recruitment_candidate_skill_rel',
        'candidate_id', 'skill_id',
        string="Skills",
        help="Candidate skill tags.")

    # Status (pipeline)
    candidate_status = fields.Selection(
        selection=[
            ('new', 'New'),
            ('screened', 'Screened'),
            ('interview', 'Interview'),
            ('selected', 'Selected'),
            ('rejected', 'Rejected'),
            ('offered', 'Offered'),
            ('joined', 'Joined'),
        ],
        string="Candidate Status", required=True, default='new',
        tracking=True)
    remarks = fields.Text(string="Remarks")

    # Relationships
    interview_ids = fields.One2many(
        'recruitment.interview', 'candidate', string="Interviews")
    offer_ids = fields.One2many(
        'recruitment.offer', 'candidate', string="Offers")
    interview_count = fields.Integer(
        compute='_compute_counts', string="Interview Count")
    offer_count = fields.Integer(
        compute='_compute_counts', string="Offer Count")

    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company)
    active = fields.Boolean(default=True)

    @api.constrains('mobile_number', 'email')
    def _check_mobile_and_email(self):
        email_pattern = re.compile(
            r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')

        for rec in self:
            if rec.mobile_number:
                digits = re.sub(r'[\s\-+]', '', rec.mobile_number)
                if not digits.isdigit():
                    raise ValidationError(_(
                        "Mobile Number can only contain digits."))
                if len(digits) < 10:
                    raise ValidationError(_(
                        "Mobile Number must be at least 10 digits."))

            if rec.email and not email_pattern.match(rec.email):
                raise ValidationError(_(
                    "Please enter a valid email address."))

    @api.depends('interview_ids', 'offer_ids')
    def _compute_counts(self):
        for rec in self:
            rec.interview_count = len(rec.interview_ids)
            rec.offer_count = len(rec.offer_ids)

    def action_view_interviews(self):
        self.ensure_one()
        return {
            'name': _('Interviews'),
            'type': 'ir.actions.act_window',
            'res_model': 'recruitment.interview',
            'view_mode': 'list,form',
            'domain': [('candidate', '=', self.id)],
            'context': {
                'default_candidate': self.id,
                'default_job_position': self.applied_position.id,
            },
        }

    def action_view_offers(self):
        self.ensure_one()
        return {
            'name': _('Offers'),
            'type': 'ir.actions.act_window',
            'res_model': 'recruitment.offer',
            'view_mode': 'list,form',
            'domain': [('candidate', '=', self.id)],
            'context': {
                'default_candidate': self.id,
                'default_job_position': self.applied_position.id,
            },
        }