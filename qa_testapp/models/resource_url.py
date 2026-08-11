import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError

# Accepts http(s) links and root-relative Odoo links (e.g. /web/content/123).
# Anything without a scheme is normalised to https:// before this runs, so the
# check below only ever sees a scheme-qualified or root-relative value.
_URL_RE = re.compile(r'^(https?://|/)', re.IGNORECASE)


class QAResourceUrl(models.Model):
    """A single reference URL attached to a Bug, Test Plan or Test Case.

    One shared line model instead of three: the three parents each own a
    One2many into it through their own column, so an inline editable list on
    every form reuses the same records, ACL and validation. Storing one URL
    per row (rather than many in a Text field) is what makes each link
    individually clickable, editable and deletable.
    """

    _name = 'qa_testapp.resource_url'
    _description = 'QA Reference URL'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    name = fields.Char(
        string='Label',
        help='Optional description shown instead of the raw link, '
             'e.g. "Screenshot of the error".',
    )
    url = fields.Char(
        string='URL', required=True,
        help='Link to evidence, a screenshot, a document or any external '
             'reference. Opens in a new tab.',
    )
    url_type = fields.Selection(
        [
            ('evidence', 'Evidence'),
            ('screenshot', 'Screenshot'),
            ('reference', 'External Reference'),
            ('document', 'Document'),
            ('other', 'Other'),
        ],
        string='Type', default='reference', required=True,
    )

    # One nullable link per parent. ondelete='cascade' so removing a Bug / Test
    # Plan / Test Case takes its URL rows with it rather than orphaning them.
    ticket_id = fields.Many2one(
        'qa_testapp.ticket', string='Bug', ondelete='cascade', index=True)
    test_plan_id = fields.Many2one(
        'qa_testapp.test_plan', string='Test Plan', ondelete='cascade', index=True)
    test_case_id = fields.Many2one(
        'qa_testapp.test_case', string='Test Case', ondelete='cascade', index=True)

    @api.model
    def _normalize_url(self, value):
        """Add a scheme when the user typed a bare host.

        'www.example.com/x' is what people paste; without a scheme the url
        widget renders it as a relative link that 404s inside Odoo. Root-
        relative links (starting '/') are left untouched.
        """
        if not value:
            return value
        value = value.strip()
        if value and not re.match(r'^([a-zA-Z][\w+.-]*:|/)', value):
            value = 'https://' + value
        return value

    @api.constrains('url')
    def _check_url(self):
        for rec in self:
            if not _URL_RE.match(rec.url or ''):
                raise ValidationError(
                    "'%s' is not a valid URL. Use a full link such as "
                    "https://example.com/page." % (rec.url or '')
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('url'):
                vals['url'] = self._normalize_url(vals['url'])
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('url'):
            vals['url'] = self._normalize_url(vals['url'])
        return super().write(vals)
