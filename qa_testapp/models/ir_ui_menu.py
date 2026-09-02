from odoo import api, models, tools

from .res_users import BUG_ONLY_GROUP_XMLID

# The only menu subtrees a bug-only tester may see. The ancestors of each root
# (the PMS root) are added automatically so the app icon itself stays reachable.
#
# Timesheets is listed here, but listing it is not what grants access: the
# filter below only ever *removes* menus from what the standard implementation
# already decided this user may see, and hr_timesheet gates its own menus on
# group_hr_timesheet_user. A tester without that group still sees nothing
# extra; the group is implied by group_qa_bug_only in security/qa_security.xml.
BUG_ONLY_MENU_XMLIDS = (
    'qa_testapp.menu_updates_bug',
    'hr_timesheet.timesheet_menu_root',
)


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    @api.model
    def _qa_bug_only_menu_ids(self):
        """Menu ids a bug-only tester is allowed to see: every whitelisted
        subtree plus the ancestors of each subtree's root.

        A root that does not resolve is skipped rather than fatal, so a
        database where one of the modules involved is not installed keeps the
        remaining subtrees instead of losing every menu.
        """
        allowed = set()
        menus = self.sudo().with_context(active_test=False)
        for xmlid in BUG_ONLY_MENU_XMLIDS:
            root = self.env.ref(xmlid, raise_if_not_found=False)
            if not root:
                continue
            allowed.update(menus.search([('id', 'child_of', root.id)]).ids)
            menu = root.sudo()
            while menu.parent_id:
                menu = menu.parent_id
                allowed.add(menu.id)
        return frozenset(allowed)

    @api.model
    @tools.ormcache('frozenset(self.env.user._get_group_ids())', 'debug')
    def _visible_menu_ids(self, debug=False):
        """Hide everything outside the Bugs menu for bug-only testers.

        Done here rather than by putting ``groups`` on the menus we want gone,
        because those menus (Test Cases, Test Plans, Test Scenarios, and the
        stock Project ones whose root had its groups cleared by ft_homepage)
        are currently open to every internal user — adding a group to them
        would change what the rest of the company sees. Filtering by group
        membership at load time leaves every other user's menu untouched.

        Cached on the same key as the base implementation, which is exactly
        the group set this override branches on.
        """
        visible = super()._visible_menu_ids(debug=debug)
        group = self.env.ref(BUG_ONLY_GROUP_XMLID, raise_if_not_found=False)
        if not group or group.id not in self.env.user._get_group_ids():
            return visible
        return frozenset(visible & self._qa_bug_only_menu_ids())
