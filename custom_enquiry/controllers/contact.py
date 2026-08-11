import json
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

try:
    from odoo.addons.website.controllers.form import WebsiteForm

    class CustomWebsiteForm(WebsiteForm):
        """
        Override Odoo's WebsiteForm controller to intercept the standard
        /contactus form submission (which POSTs to /website/form/crm.lead)
        and save it into the custom x.enquiry model instead.
        """

        @http.route('/website/form/<string:model_name>', type='http',
                    auth='public', methods=['POST'], website=True, csrf=False)
        def website_form(self, model_name, **kwargs):
            # The standard /contactus page always submits to model 'crm.lead'
            if model_name == 'crm.lead':
                name    = (kwargs.get('contact_name') or '').strip()
                phone   = (kwargs.get('phone') or '').strip()
                email   = (kwargs.get('email_from') or '').strip()
                company = (kwargs.get('partner_name') or '').strip()
                subject = (kwargs.get('subject') or 'Contact Us Enquiry').strip()
                message = (kwargs.get('description') or '').strip()

                # Fallbacks for required fields
                if not name:
                    name = 'Website Visitor'
                if not email:
                    email = 'noreply@unknown.com'
                if not subject:
                    subject = 'Contact Us Enquiry'
                if not message:
                    message = '(no message provided)'

                try:
                    record = request.env['x.enquiry'].sudo().create({
                        'x_name'   : name,
                        'x_phone'  : phone,
                        'x_email'  : email,
                        'x_company': company,
                        'x_subject': subject,
                        'x_message': message,
                    })
                    _logger.info(
                        "x.enquiry record created from /contactus form: "
                        "ID=%s, name=%s, email=%s", record.id, name, email
                    )
                    # Return JSON with the new record's ID (Odoo website_form expects this)
                    return request.make_response(
                        json.dumps({'id': record.id}),
                        headers=[('Content-Type', 'application/json')]
                    )
                except Exception as e:
                    _logger.error(
                        "custom_enquiry: Failed to create x.enquiry record: %s", e
                    )
                    # Fall back to standard Odoo behavior on error
                    return super().website_form(model_name, **kwargs)

            # For all other model form submissions, use standard Odoo behavior
            return super().website_form(model_name, **kwargs)

except ImportError:
    _logger.warning(
        "custom_enquiry: Could not import WebsiteForm from odoo.addons.website.controllers.form. "
        "The /contactus form override is NOT active."
    )