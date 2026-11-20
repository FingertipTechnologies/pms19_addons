"""CRM/PMS company/customer synchronization using standard res.partner."""
import logging
import re
from urllib.parse import urlsplit

import requests
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

COMPANY_FIELDS = {
    'name': 'name', 'website': 'website', 'email': 'email', 'phone': 'phone',
    'mobile': 'mobile', 'vat': 'vat', 'street': 'street', 'street2': 'street2',
    'city': 'city', 'zip': 'zip', 'state_id': 'state', 'country_id': 'country',
}
CONTACT_FIELDS = {
    'name': 'name', 'email': 'email', 'phone': 'phone', 'mobile': 'mobile',
    'function': 'job_title',
}


def norm_name(value):
    return re.sub(r'\s+', ' ', (value or '').strip()).casefold()


def norm_site(value):
    value = (value or '').strip().lower()
    if not value:
        return ''
    if '://' not in value:
        value = 'https://' + value
    parsed = urlsplit(value)
    host = (parsed.netloc or parsed.path).split('/')[0].split(':')[0].lower()
    return (host[4:] if host.startswith('www.') else host).rstrip('.')


def norm_email(value):
    return (value or '').strip().casefold()


def norm_mobile(value):
    return re.sub(r'[^0-9+]', '', value or '')


def contact_identity_key(name, email=None, mobile=None):
    """Identity under one company, using only identifiers supplied by sender.

    When both email and mobile are supplied, BOTH must match. If only one
    exists, match that value. For name-only contacts, use the normalized name.
    """
    email = norm_email(email)
    mobile = norm_mobile(mobile)
    if email and mobile:
        return ('email_mobile', email, mobile)
    if email:
        return ('email', email)
    if mobile:
        return ('mobile', mobile)
    return ('name', norm_name(name))


class ContactMatchError(ValidationError):
    """Ambiguous contact match, no manual-review model."""


class ResPartner(models.Model):
    _inherit = 'res.partner'
    customer_code = fields.Char(string='Customer Code', copy=False, index=True, readonly=True,tracking=True)
    erp_customer_id = fields.Char(string='ERP Customer ID', copy=False, index=True, readonly=True,tracking=True)
    erp_sync_state = fields.Selection([
        ('not_synced', 'Not Synced'), ('pending', 'Pending'),
        ('processing', 'Processing'), ('success', 'Synchronized'), ('failed', 'Failed')],
        default='not_synced', copy=False, readonly=True, index=True,tracking=True)
    erp_last_sync_date = fields.Datetime(string='Last ERP Sync', copy=False, readonly=True,tracking=True)
    erp_pending_changes = fields.Json(copy=False, readonly=True)
    _sql_constraints = [('customer_code_unique', 'unique(customer_code)', 'Customer Code must be unique.')]

    @api.constrains('customer_code', 'is_company')
    def _check_customer_code(self):
        for p in self:
            if p.customer_code and not p.is_company:
                raise ValidationError(_('Customer Code must belong to a company.'))

    def _set_customer_account_status(self):
        Status = self.env['res.partner.account.status'].sudo()
        status = Status.with_context(active_test=False).search([('name', '=ilike', 'Customer')], limit=1)
        if not status:
            status = Status.create({'name': 'Customer', 'description': 'Customer account', 'active': True})
        elif not status.active:
            status.write({'active': True})
        for p in self:
            c = p.commercial_partner_id
            if c and c.account_status_id != status:
                c.write({'account_status_id': status.id})

    def _prepare_erp_customer_payload(self):
        self.ensure_one()
        c = self.commercial_partner_id
        def get(p, attr):
            return p[attr] or '' if attr in p._fields else ''
        contacts = []
        seen_contact_keys = set()
        children = c.child_ids.filtered(
            lambda p: not p.is_company and p.type == 'contact' and p.name
        )
        # Never drop edits to an existing contact because another contact has
        # the same current identity. Keep the original dedupe for other rows.
        for partner in children.sorted(key=lambda p: not bool(p.erp_pending_changes)):
            contact = {key: get(partner, field) for field, key in CONTACT_FIELDS.items()}
            contact['source_contact_id'] = str(partner.id)
            pending = partner.erp_pending_changes or {}
            identity = contact_identity_key(contact['name'], contact['email'], contact['mobile'])
            if identity in seen_contact_keys and not pending:
                continue
            seen_contact_keys.add(identity)
            if pending:
                contact['changed_fields'] = pending['fields']
                contact['previous_identity'] = pending['previous_identity']
            contacts.append(contact)
        company = {key: get(c, field) for field, key in COMPANY_FIELDS.items()
                   if field not in ('state_id', 'country_id')}
        company.update(state=c.state_id.name or '', state_code=c.state_id.code or '',
                       country=c.country_id.code or '')
        company['changed_fields'] = (c.erp_pending_changes or {}).get('fields', [])
        payload = {'source_system': 'crm_pms', 'source_company_id': str(c.id),
                   'company': company, 'contacts': contacts}
        if c.erp_customer_id and c.customer_code:
            payload.update(erp_customer_id=c.erp_customer_id, customer_code=c.customer_code)
        return payload

    @api.model
    def _fill_empty(self, record, data, mapping):
        vals = {}
        for incoming, field_name in mapping.items():
            value = data.get(incoming)
            if value not in (None, '') and field_name in record._fields and not record[field_name]:
                vals[field_name] = value
        if vals:
            record.sudo().write(vals)
        return vals

    @api.model
    def _upsert_erp_contact(self, company, data):
        P = self.sudo().with_context(active_test=False)
        name = (data.get('name') or '').strip()
        if not name:
            return {'status': 'skipped', 'reason': 'contact_name_missing'}
        email, mobile = norm_email(data.get('email')), norm_mobile(data.get('mobile'))
        siblings = P.search([('parent_id', '=', company.id), ('is_company', '=', False), ('type', '=', 'contact')])
        incoming_key = contact_identity_key(name, email, mobile)

        def same(contact):
            # Never partially match an email+mobile pair: different populated
            # values represent different contacts, even if one matches.
            if incoming_key[0] == 'email_mobile':
                return (norm_email(contact.email) == email
                        and norm_mobile(contact.mobile) == mobile)
            if incoming_key[0] == 'email':
                return norm_email(contact.email) == email
            if incoming_key[0] == 'mobile':
                return norm_mobile(contact.mobile) == mobile
            return norm_name(contact.name) == incoming_key[1]

        matches = siblings.filtered(same)
        if len(matches) > 1:
            raise ContactMatchError(_('Multiple contacts match under company %s: %s') % (company.name, name))
        if matches:
            contact = matches[0]
            self._fill_empty(contact, data, {'name': 'name', 'email': 'email', 'phone': 'phone',
                                             'mobile': 'mobile', 'job_title': 'function'})
            return {'status': 'updated', 'crm_contact_id': contact.id}
        # No exact match for the available identifiers: create a distinct
        # contact under this company. Partial email/mobile overlaps are allowed.
        vals = {'name': name, 'parent_id': company.id, 'type': 'contact', 'is_company': False}
        for incoming, field_name in {'email': 'email', 'phone': 'phone', 'mobile': 'mobile',
                                     'job_title': 'function'}.items():
            if data.get(incoming) and field_name in P._fields:
                vals[field_name] = data[incoming]
        contact = P.create(vals)
        return {'status': 'created', 'crm_contact_id': contact.id}

    @api.model_create_multi
    def create(self, vals_list):
        """Queue an already-synchronized company when a new child contact is saved.

        The existing cron does the HTTP call. Prospect contacts are ignored.
        """
        partners = super().create(vals_list)
        company_ids = set()
        for contact in partners:
            if not contact.parent_id or contact.is_company:
                continue
            # Only actual people/contacts; ignore invoice/delivery address records.
            if contact.type != 'contact' or not contact.name:
                continue
            company = contact.parent_id.commercial_partner_id
            if company.is_company and (company.erp_sync_state == 'success'
                                       or (company.erp_customer_id and company.customer_code)):
                company_ids.add(company.id)
        if company_ids:
            self.env['res.partner'].browse(list(company_ids)).sudo().write({
                'erp_sync_state': 'pending',
            })
        return partners

    def write(self, vals):
        """Queue business edits only, preserving the pre-edit contact identity."""
        mapped = set(vals) & (COMPANY_FIELDS.keys() | CONTACT_FIELDS.keys())
        if not mapped:
            return super().write(vals)
        snapshots = []
        for partner in self:
            company = partner.commercial_partner_id
            if not company.is_company or not (company.erp_customer_id and company.customer_code):
                continue
            is_company = partner == company
            if not is_company and (partner.is_company or partner.type != 'contact'
                                   or partner.parent_id != company):
                continue
            mapping = COMPANY_FIELDS if is_company else CONTACT_FIELDS
            previous = {field: partner[field] for field in mapped & mapping.keys()}
            if previous:
                identity = (None if is_company else {
                    key: (partner[key] or '') if key in partner._fields else ''
                    for key in ('name', 'email', 'mobile')
                })
                snapshots.append((partner, company, mapping, previous, identity))
        if snapshots:
            # The cron locks the company first when setting Processing. Use
            # the same order so it cannot acknowledge a concurrent contact edit.
            company_ids = sorted({company.id for _, company, _, _, _ in snapshots})
            self.env.cr.execute(
                'SELECT id FROM res_partner WHERE id IN %s ORDER BY id FOR UPDATE',
                (tuple(company_ids),),
            )
        result = super().write(vals)
        for partner, company, mapping, previous, identity in snapshots:
            if partner != company and (partner.parent_id != company or partner.type != 'contact'
                                       or partner.is_company):
                continue
            changes = {mapping[field] for field, old in previous.items()
                       if partner[field] and partner[field] != old}
            if not changes:
                continue
            pending = dict(partner.erp_pending_changes or {})
            pending['fields'] = sorted(set(pending.get('fields', [])) | changes)
            if identity is not None:
                pending.setdefault('previous_identity', identity)
            partner.sudo().write({'erp_pending_changes': pending})
            company.sudo().write({'erp_sync_state': 'pending'})
        return result

    def _queue_erp_customer(self):
        for p in self:
            c = p.commercial_partner_id
            if c.is_company:
                c.sudo().write({'erp_sync_state': 'pending'})

    def _send_to_erp(self):
        self.ensure_one()
        c = self.commercial_partner_id
        c.sudo().write({'erp_sync_state': 'processing'})
        try:
            config = self.env['ir.config_parameter'].sudo()
            url = (config.get_param('crm_erp_customer_sync.api_url') or '').strip()
            token = (config.get_param('crm_erp_customer_sync.api_token') or '').strip()
            if not url or not token:
                raise UserError(_('Configure ERP API URL and Bearer token.'))
            if not (url.startswith('https://') or url.startswith('http://localhost:')
                    or url.startswith('http://127.0.0.1:')):
                raise UserError(_('Use HTTPS or localhost for ERP API URL.'))
            payload = c._prepare_erp_customer_payload()
            if not payload.get('erp_customer_id') and (
                not payload['company']['name'] or not payload['company']['website']
            ):
                raise UserError(_('Company name and website are required for the first sync.'))
            response = requests.post(url, json=payload,
                                     headers={'Content-Type': 'application/json', 'Accept': 'application/json',
                                              'Authorization': 'Bearer ' + token},
                                     timeout=(5, 30), allow_redirects=False)
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict) or result.get('success') is not True:
                raise UserError(_('ERP did not confirm synchronization.'))
            customer = result.get('customer') or {}
            code, erp_id = customer.get('customer_code'), customer.get('erp_customer_id')
            if not code or not erp_id:
                raise UserError(_('ERP response lacks customer_code or erp_customer_id.'))
            if payload.get('erp_customer_id') and (
                str(erp_id) != payload['erp_customer_id'] or code != payload['customer_code']
            ):
                raise UserError(_('ERP returned a different customer ID or Customer Code.'))
            edited_contacts = {item['source_contact_id'] for item in payload['contacts']
                               if item.get('changed_fields')}
            if payload['company']['changed_fields'] or edited_contacts:
                if result.get('change_sync_version') != 1:
                    raise UserError(_('Upgrade the ERP receiver before syncing edits.'))
                confirmed = {str(item.get('source_contact_id')) for item in result.get('contacts', [])
                             if item.get('erp_contact_id')}
                if not edited_contacts <= confirmed:
                    raise UserError(_('ERP did not confirm all edited contacts.'))
                c.child_ids.filtered(lambda p: str(p.id) in edited_contacts).sudo().write({
                    'erp_pending_changes': False,
                })
            c.sudo().write({'customer_code': code, 'erp_customer_id': str(erp_id),
                            'erp_pending_changes': False, 'erp_sync_state': 'success',
                            'erp_last_sync_date': fields.Datetime.now()})
            return True
        except Exception as exc:
            _logger.exception('ERP sync failed for partner %s: %s', c.id, exc)
            c.sudo().write({'erp_sync_state': 'failed'})
            return False

    @api.model
    def _cron_process_erp_sync(self):
        """Send a small batch of queued Won companies to ERP each minute.

        Only pending companies are selected. Failed ones remain failed until
        explicitly re-queued via the historical/bulk action. A company is
        marked success only after ERP confirms its ID and customer code.
        """
        companies = self.sudo().search([
            ('is_company', '=', True),
            ('erp_sync_state', '=', 'pending'),
        ], order='id', limit=10)
        for company in companies:
            try:
                # Isolate any unexpected exception to the individual company.
                with self.env.cr.savepoint():
                    company._send_to_erp()
            except Exception:
                _logger.exception('Unexpected scheduled ERP sync error for company %s', company.id)
                with self.env.cr.savepoint():
                    company.sudo().write({'erp_sync_state': 'failed'})
        return True
