# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.mail import single_email_re


def _pwf_split_emails(raw):
    """Plain addresses in a comma / semicolon separated string."""
    return [chunk.strip() for chunk in (raw or '').replace(';', ',').split(',')
            if chunk.strip()]


class ResCompany(models.Model):
    _inherit = 'res.company'

    pwf_stage_notify_partner_ids = fields.Many2many(
        'res.partner', 'res_company_pwf_stage_notify_partner_rel',
        'company_id', 'partner_id',
        string='Stage Change Recipients',
        help='Contacts notified by e-mail whenever a project changes stage.',
    )
    pwf_stage_notify_email = fields.Char(
        string='Stage Change Info E-mail',
        help='Additional address(es) notified whenever a project changes '
             'stage. Separate several addresses with a comma.',
    )

    @api.constrains('pwf_stage_notify_email')
    def _check_pwf_stage_notify_email(self):
        for company in self:
            raw = (company.pwf_stage_notify_email or '').strip()
            if not raw:
                continue
            invalid = [e for e in _pwf_split_emails(raw) if not single_email_re.match(e)]
            if invalid or not _pwf_split_emails(raw):
                raise ValidationError(_(
                    "Invalid stage change info e-mail: %s. Enter plain "
                    "addresses such as name@domain.com, separated by commas.",
                    ', '.join(invalid) or raw))

    def _pwf_stage_notify_emails(self):
        """Lower-cased, de-duplicated info addresses of this company."""
        self.ensure_one()
        result = []
        for email in _pwf_split_emails(self.pwf_stage_notify_email):
            email = email.lower()
            if single_email_re.match(email) and email not in result:
                result.append(email)
        return result
