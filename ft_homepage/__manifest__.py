# -*- coding: utf-8 -*-
{
    "name": "FT Homepage – App Access, Landing Page & Announcements",
    # 18.0.1.2.0 routes all text to the upper-right panel, caps what may be
    # active at once (4 media, 1 text), and limits text length so the panel
    # never truncates.
    # 18.0.1.2.1 enforces that text length in the form as it is typed, with a
    # character counter, instead of only on save.
    # 18.0.1.2.2 stops the upgrade aborting on a database that does not have
    # every optional app: the menu access matrix now skips what is not
    # installed instead of asserting on it.
    "version": "19.0.1.2.2",
    "category": "Productivity",
    "summary": "Role-based app icon visibility, default Homepage landing page, "
                "and Quote of the Day / Announcement widget on the Homepage.",
    "description": """
FT Homepage
===========
Implements 3 requirements on top of the Homepage (web_responsive Apps Menu grid):

1. App Icon Visibility by Role
   Restricts which app icons show on the Homepage grid using ir.ui.menu
   security groups, per the access matrix (see data/menu_access_data.xml).

2. Default Landing Page after Login
   Adds a system-wide setting (Settings > General Settings) that makes the
   Homepage (Apps Menu grid) the default landing page after login for all
   users, instead of Discuss / Invoicing. Built on top of web_responsive's
   `is_redirect_home` field on res.users.

3. Quote of the Day / Announcement Widget
   Adds a "Quote / Announcement" model (text, image or video, with
   contributor name) that is rendered below the app icons on the Homepage,
   with a decorative quote style for text and a marquee scroll animation.
""",
    "author": "Fingertip",
    "website": "",
    "license": "LGPL-3",
    "depends": [
        "base",
        "web",
        "mail",
        "web_responsive",
        "general",
        "project",
        "hr",
       
        "crm",
        "sale",
        "mass_mailing",
        "account",
        "link_tracker",
        "website",
        "calendar",
        "website_slides",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/menu_access_data.xml",
        "data/apply_landing_page.xml",
        "views/quote_announcement_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "ft_homepage/static/src/homepage/quote_widget.scss",
            "ft_homepage/static/src/homepage/quote_widget.js",
            "ft_homepage/static/src/homepage/quote_widget.xml",
            # Field widget for the announcement form, not the Homepage itself.
            "ft_homepage/static/src/homepage/limited_text_field.js",
            "ft_homepage/static/src/homepage/limited_text_field.xml",
        ],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
}
