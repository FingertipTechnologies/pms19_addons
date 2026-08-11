from odoo import models, fields, api

class MarketingScorecard(models.Model):
    _name = "marketing.scorecard"
    _description = "Marketing Scorecard"
    _rec_name = "name"

    name = fields.Char(
        string="Scorecard Name",
        compute="_compute_name",
        store=True
    )
    date = fields.Date(
        string='Date',
        default=fields.Date.context_today
    )

    videos = fields.Integer(string="Videos")
    posts = fields.Integer(string="Posts")
    leads = fields.Integer(string="Leads")

    seo_activity = fields.Text(string="SEO Activity")
    fb_campaigns = fields.Integer(string="FB Campaigns")
    email_campaigns = fields.Integer(string="Email Campaigns")
    linkedin_campaigns = fields.Integer(string="Email Campaigns")

    fb_leads = fields.Integer(string="FB Leads")
    linkedin_leads = fields.Integer(string="LinkedIn Leads")
    email_leads = fields.Integer(string="Email Leads")
    description = fields.Text(
        string="Description"
    )
    
    @api.depends('date')
    def _compute_name(self):
        for record in self:
            if record.date:
                record.name = f"Marketing Scorecard - {record.date}"
            else:
                record.name = "Marketing Scorecard"

