# -*- coding: utf-8 -*-
from odoo import api, fields, models


class RecruitmentInterview(models.Model):
    _name = "recruitment.interview"
    _description = "Recruitment Interview"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "interview_date desc"
    _rec_name = "display_name"

    display_name = fields.Char(
        compute='_compute_display_name', store=True)

    candidate = fields.Many2one(
        'recruitment.candidate', string="Candidate", required=True,
        tracking=True, ondelete='cascade')
    job_position = fields.Many2one(
        'recruitment.job.position', string="Job Position",
        required=True, tracking=True)
    interview_round = fields.Selection(
        selection=[
            ('hr', 'HR'),
            ('technical_1', 'Technical 1'),
            ('technical_2', 'Technical 2'),
            ('management', 'Management'),
            ('client', 'Client'),
        ],
        string="Interview Round", required=True, tracking=True)

    # Schedule
    interview_date = fields.Datetime(
        string="Interview Date", required=True, tracking=True)
    interview_mode = fields.Selection(
        selection=[
            ('online', 'Online'),
            ('offline', 'Offline'),
            ('phone', 'Phone'),
        ],
        string="Interview Mode", required=True, default='online')
    interviewer = fields.Many2one(
        'hr.employee', string="Interviewer", required=True, tracking=True)
    meeting_link = fields.Char(string="Meeting Link")

    # Result
    status = fields.Selection(
        selection=[
            ('scheduled', 'Scheduled'),
            ('completed', 'Completed'),
            ('no_show', 'No Show'),
            ('cancelled', 'Cancelled'),
        ],
        string="Status", required=True, default='scheduled', tracking=True)
    feedback = fields.Text(string="Feedback")
    rating = fields.Selection(
        selection=[
            ('1', '1 - Poor'),
            ('2', '2 - Below Average'),
            ('3', '3 - Average'),
            ('4', '4 - Good'),
            ('5', '5 - Excellent'),
        ],
        string="Rating")
    result = fields.Selection(
        selection=[
            ('selected', 'Selected'),
            ('rejected', 'Rejected'),
            ('hold', 'Hold'),
        ],
        string="Result", tracking=True)
    next_round_required = fields.Boolean(string="Next Round Required")

    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company)

    @api.depends('candidate.candidate_name', 'interview_round',
                 'interview_date')
    def _compute_display_name(self):
        round_dict = dict(self._fields['interview_round'].selection)
        for rec in self:
            rec.display_name = "%s — %s — %s" % (
                rec.candidate.candidate_name or '',
                round_dict.get(rec.interview_round, '') or '',
                rec.interview_date or '')

    def write(self, vals):
        res = super().write(vals)
        # Sync candidate status when the interview is marked completed.
        if vals.get('status') == 'completed':
            for rec in self:
                if rec.result == 'selected':
                    rec.candidate.candidate_status = (
                        'selected' if not rec.next_round_required
                        else 'interview')
                elif rec.result == 'rejected':
                    rec.candidate.candidate_status = 'rejected'
        return res