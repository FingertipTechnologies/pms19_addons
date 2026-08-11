import re

from odoo import models, fields, api, _
from odoo.tools import html2plaintext

# Characters of the description shown in the list before truncating. Long enough
# to be useful at a glance, short enough that the column can't push the row.
PREVIEW_LEN = 160

# html2plaintext footnotes images and links: an <img> becomes "Image [1]" with
# the src appended at the end. Trainees paste screenshots, and a pasted image is
# a base64 data URI — so a single screenshot would pour tens of thousands of
# characters of base64 into the preview text (and the first 160 of them onto the
# screen). Strip images out, and unwrap links to their text, before converting.
# Doing it on the HTML means the base64 never reaches the converter at all.
IMG_TAG_RE = re.compile(r'<img\b[^>]*>', re.I)
ANCHOR_TAG_RE = re.compile(r'</?a\b[^>]*>', re.I)


class TodayLearning(models.Model):
    _name = 'ft.today.learning'
    _description = "Today's Learning"
    _order = 'create_date desc'
    _rec_name = 'learning_topic_id'

    learning_topic_id = fields.Many2one(
        'ft.learning.topic', string='Learning Topic', required=True,
        ondelete='restrict',
    )
    description = fields.Html(
        string='Description',
        help='What you learned. Rich text — supports formatting and images.',
    )
    description_preview = fields.Char(
        string='What Did You Learn?',
        compute='_compute_description_preview',
        help="Plain-text opening of the description, for the list view. The "
             "description itself is rich text: rendered as-is in a list it would "
             "bring its markup and images with it and stretch the row.",
    )
    # No manual date field: the system Created Date is used instead.
    # create_date / create_uid are provided automatically by Odoo.

    @api.depends('description')
    def _compute_description_preview(self):
        for rec in self:
            if not rec.description:
                rec.description_preview = ''
                continue
            html = IMG_TAG_RE.sub(' ', rec.description)
            html = ANCHOR_TAG_RE.sub('', html)
            # html2plaintext turns block tags into newlines; collapse all
            # whitespace so a multi-paragraph entry stays on one line.
            text = ' '.join(html2plaintext(html).split())
            rec.description_preview = (
                text[:PREVIEW_LEN].rstrip() + '…' if len(text) > PREVIEW_LEN else text
            )

    def _compute_display_name(self):
        # Odoo 19 removed name_get(); display_name is computed instead.
        for rec in self:
            topic = rec.learning_topic_id.name or _("Learning")
            day = fields.Date.to_string(rec.create_date) if rec.create_date else ''
            rec.display_name = f"{topic} ({day})" if day else topic
