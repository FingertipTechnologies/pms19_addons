# Part of Odoo. See LICENSE file for full copyright and licensing details.

import base64
import io
import logging


from contextlib import nullcontext
try:
    from werkzeug.utils import send_file
except ImportError:
    from odoo.tools._vendor.send_file import send_file

import odoo
import odoo.modules.registry
from odoo import SUPERUSER_ID, _, http, api
from odoo.http import request, Response
from odoo.tools import file_open, file_path, replace_exceptions, str2bool
from odoo.tools.mimetypes import guess_mimetype

_logger = logging.getLogger(__name__)

class Binary(http.Controller):
    
    @http.route([
        '/web/binary/company_logo',
        '/logo',
        '/logo.png',
    ], type='http', auth="none", cors="*")
    def company_logo(self, dbname=None, **kw):
        imgname = 'logo'
        imgext = '.png'
        dbname = request.db
        uid = (request.session.uid if dbname else None) or odoo.SUPERUSER_ID

        if not dbname:
            response = http.Stream.from_path(file_path('web/static/img/logo.png')).get_response()
        else:
            try:
                company = int(kw['company']) if kw and kw.get('company') else False
                if company:
                    request.env.cr.execute("""
                        SELECT COALESCE(portal_login_page_image_web, logo_web) as logo_web, write_date
                          FROM res_company
                         WHERE id = %s
                    """, (company,))
                else:
                    request.env.cr.execute("""
                        SELECT COALESCE(c.portal_login_page_image_web, c.logo_web) as logo_web, c.write_date
                          FROM res_users u
                     LEFT JOIN res_company c
                            ON c.id = u.company_id
                         WHERE u.id = %s
                    """, (uid,))
                row = request.env.cr.fetchone()
                if row and row[0]:
                    image_base64 = base64.b64decode(row[0])
                    image_data = io.BytesIO(image_base64)
                    mimetype = guess_mimetype(image_base64, default='image/png')
                    imgext = '.' + mimetype.split('/')[1]
                    if imgext == '.svg+xml':
                        imgext = '.svg'
                    response = send_file(
                        image_data,
                        request.httprequest.environ,
                        download_name=imgname + imgext,
                        mimetype=mimetype,
                        last_modified=row[1],
                        response_class=Response,
                    )
                else:
                    response = http.Stream.from_path(file_path('web/static/img/nologo.png')).get_response()
            except Exception:
                _logger.warning("While retrieving the company logo, using the Odoo logo instead", exc_info=True)
                response = http.Stream.from_path(file_path(f'web/static/img/{imgname}{imgext}')).get_response()

        return response