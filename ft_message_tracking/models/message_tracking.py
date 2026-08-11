import uuid

from odoo import api, fields, models


class MessageTracking(models.Model):
    _name = 'ft.message.tracking'
    _description = 'Outbound Message Tracking (WhatsApp / Email)'
    _order = 'sent_time desc, id desc'
    _rec_name = 'display_name'

    from_number = fields.Char(string='From Number')
    to_number = fields.Char(string='To Number')
    message_type = fields.Selection(
        [('whatsapp', 'WhatsApp'), ('email', 'Email')],
        string='Type',
        required=True,
    )
    direction = fields.Selection(
        [('outbound', 'Outbound'), ('inbound', 'Inbound')],
        string='Direction',
        required=True,
        default='outbound',
    )
    opened = fields.Boolean(string='Opened', default=False)
    open_count = fields.Integer(string='# Open', default=0)
    last_open_time = fields.Datetime(string='Last Open Time')
    sent_time = fields.Datetime(
        string='Sent Time',
        default=fields.Datetime.now,
    )
    partner_id = fields.Many2one('res.partner', string='Contact')
    subject = fields.Char(string='Subject')
    external_message_id = fields.Char(
        string='External Message ID',
        help='Provider message ID used to match delivery / read webhooks back to this record.',
    )
    tracking_token = fields.Char(
        string='Tracking Token',
        copy=False,
        index=True,
        help='Unique token used by the email open-pixel endpoint.',
    )
    display_name = fields.Char(compute='_compute_display_name', store=True)

    @api.depends('message_type', 'to_number', 'subject', 'sent_time')
    def _compute_display_name(self):
        for rec in self:
            label = dict(rec._fields['message_type'].selection).get(rec.message_type, '')
            target = rec.to_number or rec.subject or ''
            rec.display_name = f'[{label}] {target}'.strip()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('message_type') == 'email' and not vals.get('tracking_token'):
                vals['tracking_token'] = uuid.uuid4().hex
        return super().create(vals_list)

    def register_open(self):
        now = fields.Datetime.now()
        for rec in self:
            rec.write({
                'opened': True,
                'open_count': rec.open_count + 1,
                'last_open_time': now,
            })
