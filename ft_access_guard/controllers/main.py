# -*- coding: utf-8 -*-
from odoo import _, SUPERUSER_ID
from odoo.exceptions import AccessError
from odoo.http import request, route

from odoo.addons.web.controllers.action import Action


class FtAccessGuardAction(Action):
    """Validate a user's access to an action **before** the page is returned.

    Odoo's stock ``/web/action/load`` reads the action with ``sudo()`` (see
    ``web/controllers/action.py``), so a group-restricted menu only hides the
    icon and the action's ``group_ids`` is not enforced on a direct/shared
    link. We re-check the *real* user here and raise ``AccessError`` (rendered
    by the web client as an "Access Denied" dialog) when the role is not
    allowed to open the requested action.
    """

    @route()
    def load(self, action_id, context=None):
        result = super().load(action_id, context=context)
        if isinstance(result, dict):
            self._ft_validate_action_access(result.get("id"), result.get("type"))
        return result

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------
    def _ft_validate_action_access(self, action_db_id, action_type):
        if not action_db_id or not action_type:
            return
        if not action_type.startswith("ir.actions."):
            return

        env = request.env
        user = env.user

        # The superuser and Administrators (Settings / base.group_system)
        # may open anything. The requirement is only that *restricted* roles
        # (e.g. Trainees) cannot use a shared link to reach a page their role
        # does not grant — so an admin who shares the link keeps full access.
        if user.id == SUPERUSER_ID or user.has_group("base.group_system"):
            return

        action = env[action_type].sudo().browse(int(action_db_id)).exists()
        if not action:
            return

        group_ids = set(user._get_group_ids())

        # 1) Action-level group restriction (defense in depth — Odoo does not
        #    enforce this on a sudo'd direct load).
        if "group_ids" in action._fields:
            action_groups = action.group_ids.ids
            if action_groups and set(action_groups).isdisjoint(group_ids):
                raise AccessError(self._ft_access_denied_message())

        # 2) Menu-path reachability. If the action is exposed through one or
        #    more menus, the user must be able to walk at least one full menu
        #    path (app root -> leaf) that opens it without hitting a group
        #    their role lacks. Actions that are not on any menu (e.g. opened
        #    from a button) are left alone — record-level access rights still
        #    apply to them.
        menu_model = env["ir.ui.menu"].sudo().with_context(
            **{"ir.ui.menu.full_list": True, "active_test": False}
        )
        menus = menu_model.search(
            [("action", "=", "%s,%s" % (action_type, action_db_id))]
        )
        if menus and not any(
            self._ft_menu_path_open(menu, group_ids) for menu in menus
        ):
            raise AccessError(self._ft_access_denied_message())

    @staticmethod
    def _ft_menu_path_open(menu, group_ids):
        """True if every menu from ``menu`` up to its app root is reachable by
        a user holding ``group_ids`` (a menu with no groups is open to all)."""
        node = menu
        while node:
            node_groups = node.group_ids.ids
            if node_groups and set(node_groups).isdisjoint(group_ids):
                return False
            node = node.parent_id
        return True

    @staticmethod
    def _ft_access_denied_message():
        return _(
            "Access Denied — you are not authorized to open this page.\n\n"
            "This link may have been shared with you, but your current role "
            "does not grant access to this module or feature. Please contact "
            "your administrator if you believe you should have access."
        )
