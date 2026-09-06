# -*- coding: utf-8 -*-
from odoo import http
from odoo.addons.web.controllers.utils import is_user_internal
from odoo.http import request

from odoo.addons.website.controllers.main import Website


class FtRootRedirect(Website):

    @http.route('/', auth='public', website=True, sitemap=True)
    def index(self, **kw):
        """Serve the login page on the portal root.

        The website homepage was never designed for this domain, so the stock
        controller renders an empty placeholder page. Anonymous visitors are
        better served by the login form; authenticated ones by their usual
        landing page (`/odoo` for internal users, `/my` for portal users).
        """
        uid = request.session.uid
        if not uid:
            target = '/web/login'
        elif is_user_internal(uid):
            # Do not involve the website/portal login redirect chain for
            # employees.  /odoo is Odoo's standard backend route and remains
            # entirely owned by the web module.
            target = '/odoo'
        else:
            # Keep the normal portal post-login extension point.  The portal
            # module defaults this to /my and custom portal modules may choose
            # a more specific homepage.
            target = self._login_redirect(uid)

        current_path = request.httprequest.path.rstrip('/') or '/'
        target_path = target.partition('?')[0].rstrip('/') or '/'
        if current_path == target_path:
            return super().index(**kw)

        return request.redirect(target)
