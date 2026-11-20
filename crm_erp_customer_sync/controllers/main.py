"""ERP -> CRM/PMS: match existing company and update ERP-owned code only."""
import hmac
import json
import logging

from odoo import http, fields
from odoo.http import request
from ..models.res_partner import norm_name, norm_site

_logger = logging.getLogger(__name__)


class ErpCustomerCodeApi(http.Controller):
    @staticmethod
    def _json(data, status):
        return request.make_response(
            json.dumps(data),
            headers=[('Content-Type', 'application/json; charset=utf-8')],
            status=status,
        )

    @http.route('/api/v1/erp/customer-code/sync', type='http', auth='public',
                methods=['POST'], csrf=False, save_session=False)
    def sync_customer_code(self, **kwargs):
        config = request.env['ir.config_parameter'].sudo()
        expected = config.get_param('crm_erp_customer_sync.receiver_token', '')
        authorization = request.httprequest.headers.get('Authorization', '')
        token = authorization[7:].strip() if authorization.lower().startswith('bearer ') else ''
        if not expected or not token or not hmac.compare_digest(expected, token):
            return self._json({'success': False, 'error': 'unauthorized'}, 401)
        if not request.httprequest.is_json:
            return self._json({'success': False, 'error': 'invalid_content_type'}, 415)
        try:
            payload = request.httprequest.get_json(silent=False)
        except Exception:
            return self._json({'success': False, 'error': 'invalid_json'}, 400)
        if not isinstance(payload, dict) or not isinstance(payload.get('company'), dict):
            return self._json({'success': False, 'error': 'invalid_payload'}, 400)
        data = payload['company']
        name = norm_name(data.get('name'))
        website = norm_site(data.get('website'))
        code = str(payload.get('customer_code') or '').strip()
        erp_id = str(payload.get('erp_customer_id') or '').strip()
        if not name or not website or not code or not erp_id:
            return self._json({'success': False, 'error': 'missing_fields',
                               'message': 'name, website, customer_code and erp_customer_id are required.'}, 400)
        P = request.env['res.partner'].sudo().with_context(active_test=False)
        try:
            with request.env.cr.savepoint():
                # Name + website are BOTH required. No creation on no match.
                candidates = P.search([('is_company', '=', True), ('website', '!=', False)])
                matches = candidates.filtered(
                    lambda partner: norm_name(partner.name) == name
                    and norm_site(partner.website) == website
                )
                if not matches:
                    return self._json({'success': True, 'matched': False,
                                       'message': 'No exact CRM/PMS company match. No changes made.'}, 200)
                if len(matches) > 1:
                    return self._json({'success': False, 'error': 'duplicate_exact_match',
                                       'message': 'More than one CRM/PMS company matches name and website.'}, 409)
                company = matches[0]
                # Do not give one ERP code to multiple CRM companies.
                code_owner = P.search([('customer_code', '=', code),
                                       ('is_company', '=', True), ('id', '!=', company.id)], limit=1)
                if code_owner:
                    return self._json({'success': False, 'error': 'customer_code_conflict',
                                       'message': 'ERP customer code belongs to another CRM/PMS company.'}, 409)
                vals = {}
                if company.customer_code != code:
                    vals['customer_code'] = code
                if company.erp_customer_id != erp_id:
                    vals['erp_customer_id'] = erp_id
                if company.erp_sync_state != 'success':
                    vals['erp_sync_state'] = 'success'
                if vals:
                    vals['erp_last_sync_date'] = fields.Datetime.now()
                    company.write(vals)
                company._set_customer_account_status()
                result = {'success': True, 'matched': True,
                          'customer': {'crm_customer_id': company.id,
                                       'customer_code': company.customer_code},
                          'message': 'Existing company code and Account Status synchronized.'}
            return self._json(result, 200)
        except Exception:
            _logger.exception('ERP customer code sync failed in CRM/PMS')
            return self._json({'success': False, 'error': 'processing_error'}, 500)
