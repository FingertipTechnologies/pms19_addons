# -*- coding: utf-8 -*-
{
    "name": "FT Portal Root Redirect",
    "version": "19.0.1.0.0",
    "category": "Website",
    "summary": "Send the website root (/) to the login page instead of the "
               "unused website homepage.",
    "description": """
FT Portal Root Redirect
=======================
The portal domain (portal.fingertipplus.com) serves the `website` module's
homepage on `/`. That homepage was never built out - it still holds the default
"Embed Code" placeholder snippet - so visitors land on a blank white page.

This module overrides the website root controller so that:

* anonymous visitors are redirected to `/web/login`
* already authenticated users are sent to their normal landing page
  (`/odoo` for internal users, `/my` for portal users) instead of being
  shown a login form they no longer need

The website editor is unaffected: it is reachable through `/@/` as usual, so
the homepage can still be designed later. Uninstall this module to restore the
stock behaviour.
""",
    "author": "Fingertip",
    "license": "LGPL-3",
    "depends": [
        "website",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
