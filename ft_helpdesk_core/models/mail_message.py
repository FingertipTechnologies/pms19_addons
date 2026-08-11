from markupsafe import Markup

from odoo import fields, models


class MailMessage(models.Model):
    _inherit = 'mail.message'

    # Rendered HTML list of clickable download links for this message's
    # attachments. Used by the Customer Conversation pane on the ticket form
    # so the user can click a filename to download — the standard
    # many2many_binary widget inside an X2M list row gets swallowed by the
    # row-click handler (which opens the message form view instead).
    attachment_links_html = fields.Html(
        compute='_compute_attachment_links_html',
        string='Attachments',
        sanitize=False,
    )

    def _compute_attachment_links_html(self):
        for msg in self:
            atts = msg.attachment_ids
            if not atts:
                msg.attachment_links_html = False
                continue
            parts = []
            for att in atts:
                url = '/web/content/%d?download=true' % att.id
                name = att.name or 'attachment'
                parts.append(
                    '<a href="%s" target="_blank" class="text-primary me-2">'
                    '<i class="fa fa-paperclip me-1"></i>%s</a>'
                    % (url, name)
                )
            msg.attachment_links_html = Markup(''.join(parts))
