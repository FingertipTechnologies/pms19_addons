# -*- coding: utf-8 -*-
from odoo import api, fields, models


class RecruitmentOffer(models.Model):
    _name = "recruitment.offer"
    _description = "Recruitment Offer"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "offer_date desc, id desc"
    _rec_name = "name"

    name = fields.Char(
        string="Reference", compute="_compute_name",
        store=True, readonly=True)

    candidate = fields.Many2one(
        'recruitment.candidate', string="Candidate", required=True,
        tracking=True, ondelete='cascade')
    job_position = fields.Many2one(
        'recruitment.job.position', string="Job Position",
        required=True, tracking=True)

    # Compensation
    offered_ctc = fields.Monetary(string="Offered CTC", required=True)
    joining_bonus = fields.Monetary(string="Joining Bonus")
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id)

    # Dates
    offer_date = fields.Date(
        string="Offer Date", required=True, tracking=True)
    expected_joining_date = fields.Date(string="Expected Joining Date")

    # Status
    offer_status = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('sent', 'Sent'),
            ('accepted', 'Accepted'),
            ('rejected', 'Rejected'),
            ('withdrawn', 'Withdrawn'),
        ],
        string="Offer Status", required=True, default='draft',
        tracking=True)

    # Documents
    offer_letter_attachment = fields.Many2many(
        'ir.attachment', 'recruitment_offer_attachment_rel',
        'offer_id', 'attachment_id', string="Offer Letter Attachment")
    remarks = fields.Text(string="Remarks")

    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company)

    @api.depends('candidate.candidate_name', 'job_position.job_title')
    def _compute_name(self):
        for rec in self:
            rec.name = "%s — %s" % (
                rec.candidate.candidate_name or '',
                rec.job_position.job_title or '')

    def write(self, vals):
        res = super().write(vals)
        # When offer is accepted, mark the candidate as offered.
        if vals.get('offer_status') == 'accepted':
            for rec in self:
                rec.candidate.candidate_status = 'offered'
        return res