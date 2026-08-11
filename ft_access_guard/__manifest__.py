# -*- coding: utf-8 -*-
{
    "name": "FT Access Guard – Shared Link / Direct URL Validation",
    "version": "19.0.1.0.0",
    "category": "Extra Tools",
    "summary": "Blocks direct/shared URLs to actions a user's role is not "
               "allowed to open, and shows an Access Denied message.",
    "description": """
FT Access Guard
===============
Closes a gap in Odoo's default behaviour: the backend ``/web/action/load``
route reads the requested action with ``sudo()``, so the action's own
``groups_id`` is **not** enforced and hiding a menu with ``groups_id`` only
hides it from the UI. That means a restricted user (e.g. a Trainee) who is
handed a **direct / shared link** to a page — ``/odoo/action-56``,
``/web#action=…`` or an action XML-id — can still open modules/features
their role should not see, as long as the underlying model grants them read
access.

This module validates access **server-side, before the page is returned**:

* When an action is loaded, the *real* (non-sudo) user is checked against
  1. the action's ``groups_id`` (if any), and
  2. the **menu hierarchy** that exposes the action — the user must be able
     to walk at least one full menu path (app root → leaf) that opens the
     action without hitting a group their role lacks. This reuses the
     role-based menu matrix (see ``ft_homepage`` / ``menu_access_data.xml``)
     instead of duplicating group data onto every action.
* If neither check passes, an **Access Denied** error is raised and the page
  is never displayed — regardless of URL manipulation or shared links.

Administrators (``base.group_system``) and the superuser bypass the check, so
an admin sharing a link always has access themselves; only the recipient's
role is validated.
""",
    "author": "Fingertip",
    "website": "",
    "license": "LGPL-3",
    "depends": ["base", "web"],
    "data": [],
    "installable": True,
    "application": False,
    "auto_install": True,
}
