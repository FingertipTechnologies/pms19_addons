# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

from odoo.addons.website.controllers.main import Website


class FtRootRedirect(Website):

    @http.route()
    def index(self, **kw):
        """Serve the login page on the portal root.

        The website homepage was never designed for this domain, so the stock
        controller renders an empty placeholder page. Anonymous visitors are
        better served by the login form; authenticated ones by their usual
        landing page (`/odoo` for internal users, `/my` for portal users).
        """
        if request.session.uid:
            return request.redirect(self._login_redirect(request.session.uid))
        return request.redirect('/web/login')
