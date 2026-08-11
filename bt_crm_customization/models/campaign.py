from odoo import api, fields, models
from odoo.exceptions import ValidationError

# Single source of truth for the channel list. Shared by cus.campaign.source
# and crm.lead.lead_source so a lead, an opportunity and the campaign it came
# from always speak about the same set of channels.
SOURCE_SELECTION = [
    ('linkedin', 'LinkedIn'),
    ('meta', 'Meta'),
    ('whatsapp', 'WhatsApp'),
    ('odoo', 'Odoo'),
    ('salesforce', 'Salesforce'),
    ('website', 'Website'),
    ('youtube', 'YouTube'),
    ('google_ads', 'Google Ads'),
]


class Campaign(models.Model):
    _name = 'cus.campaign'
    _description = 'Campaign'
    _order = 'date_start desc, name'

    name = fields.Char(string='Campaign Name', required=True)
    source = fields.Selection(SOURCE_SELECTION, string='Source')
    date_start = fields.Date(string='Start Date')
    date_end = fields.Date(string='End Date')
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    amount = fields.Monetary(
        string='Amount', currency_field='currency_id',
        help="Campaign budget.",
    )
    active = fields.Boolean(string='Active', default=True)

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for campaign in self:
            if (campaign.date_start and campaign.date_end
                    and campaign.date_end < campaign.date_start):
                raise ValidationError(
                    "The End Date of campaign '%s' cannot be earlier than its "
                    "Start Date." % (campaign.name or '')
                )
