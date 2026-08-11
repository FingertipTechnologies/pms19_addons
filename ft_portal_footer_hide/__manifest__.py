# -*- coding: utf-8 -*-
{
    "name": "FT Portal Footer Hide",
    "version": "19.0.1.0.0",
    "category": "Website",
    "summary": "Remove the default website footer from the portal / helpdesk "
               "frontend pages.",
    "description": """
FT Portal Footer Hide
=====================
Every frontend page on the portal domain (portal pages, helpdesk tickets, the
PMS task pages) renders Odoo's stock website footer - the "Useful Links /
About us / Connect with us" block and the "Copyright (c) Company name" bar.
None of it was ever configured: it still carries Odoo's placeholder text,
`info@yourcompany.example.com` and `+1 555-555-5556`.

The frontend layout wraps the whole footer element in `t-if="not no_footer"`
(see `web.frontend_layout`), so this module simply sets that flag. That removes
the footer CONTENT and the copyright bar in one step - deactivating the
`website.footer_custom` view alone would leave the empty grey footer band and
the copyright line behind.

Scope: all frontend pages. If a public marketing website is ever built on this
database and needs its footer back, change the template below to inherit
`portal.frontend_layout` and guard it on the request path instead.

Uninstall this module to restore the stock footer.
""",
    "author": "Fingertip",
    "license": "LGPL-3",
    "depends": [
        "portal",
    ],
    "data": [
        "views/frontend_layout_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
