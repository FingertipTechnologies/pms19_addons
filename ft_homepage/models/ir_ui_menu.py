# -*- coding: utf-8 -*-
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

# Homepage app-icon access for apps ft_homepage does NOT depend on.
#
# The rest of the access matrix is declared as plain <record> elements in
# data/menu_access_data.xml, which is the right way to write it — but only for
# modules ft_homepage actually depends on. A `<record id="other_module.xyz">`
# for a module that is not a dependency is an assertion waiting to fire:
# convert.py's _test_xml_id requires the referenced module to be in state
# 'installed' at the moment the file is parsed, and raises
#
#     AssertionError: The ID "..." refers to an uninstalled module
#
# otherwise — aborting the whole upgrade. That is exactly what happened on
# staging, where ft_ai_sales_insights is not installed: upgrading ft_homepage
# died on a line that had nothing to do with the change being deployed.
#
# These apps are genuinely optional — a database may or may not have any of
# them — so the fix is not to add them to `depends` (that would force-install
# an AI module on every database to be allowed to hide a menu). Applying them
# from Python lets a missing app be skipped rather than fatal.
#
# Ordering caveat: with no dependency declared there is no guarantee that these
# modules are loaded before ft_homepage, so on a fresh database an app that
# installs later in the same run is skipped here and picked up the next time
# ft_homepage is upgraded. The alternative — a hard dependency — is worse, and
# this runs on every upgrade, so it is self-correcting.
#
# Each entry is (menu xml id, spec). A spec may carry:
#   'groups' — the complete list of group xml ids allowed to see the menu; an
#              empty list clears every restriction (visible to all users).
#   'active' — False removes the app from the Homepage for everyone, admins
#              included, which group restrictions cannot do since the admin
#              implies most groups.
_OPTIONAL_MENU_ACCESS = [
    # Training — All users. The root menu carries no group restriction of its
    # own either; stated here so the matrix is auditable in one place.
    ('ft_training.menu_training_root', {'groups': []}),

    # Old Helpdesk app (round icon, helpdesk_mgmt) — removed from the Homepage
    # for ALL accounts.
    ('helpdesk_mgmt.helpdesk_ticket_main_menu', {'active': False}),

    # FT Helpdesk — helpdesk roles + PMs. NOT for sales/marketing (they only
    # see it if they are also given a helpdesk role). active=True re-shows it
    # in case a previous run of ft_app_menu_cleanup (which used to list
    # "Helpdesk") had hidden it.
    ('ft_helpdesk_core.menu_ft_helpdesk_root', {
        'active': True,
        'groups': [
            'ft_helpdesk_core.group_ft_helpdesk_agent',
            'project.group_project_manager',
        ],
    }),

    # Scorecard — PMs + Project Coordinators only.
    ('Project_Scorecards.menu_project_scorecard_root', {
        'groups': [
            'project.group_project_manager',
            'ft_homepage.group_project_coordinator',
        ],
    }),

    # Dashboard — Admin only.
    ('spreadsheet_dashboard.spreadsheet_dashboard_menu_root', {
        'groups': ['base.group_system'],
    }),

    # AI Insights — Admin only.
    ('ft_ai_sales_insights.menu_ai_insights_root', {
        'groups': ['base.group_system'],
    }),

    # KPI (module ft_target_management, labels renamed from Target) — whoever
    # holds a KPI role. The module ships its own "KPI / User" and
    # "KPI / Manager" groups, assigned per user from Settings > Users; Manager
    # implies User, and base.group_system implies Manager, so listing User
    # alone covers managers and admins too.
    ('ft_target_management.menu_ft_target_root', {
        'groups': ['ft_target_management.group_ft_target_user'],
    }),

    # QA Techstar Test App — hide for everyone (already covered inside
    # PMS/Project; kept installed but removed from the Homepage entirely).
    ('qa_testapp.qa_testapp_menu_root', {'active': False}),
]


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    @api.model
    def _ft_apply_optional_menu_access(self):
        """Apply _OPTIONAL_MENU_ACCESS, skipping whatever is not installed.

        Called from data/menu_access_data.xml, so it runs on install and on
        every upgrade of ft_homepage — the same schedule the <record> elements
        beside it follow, and idempotent for the same reason.

        sudo() because this is a system-level menu configuration that must
        apply whoever triggered the upgrade, and ir.ui.menu is writable by
        Settings users only.
        """
        applied, skipped = [], []
        for menu_xmlid, spec in _OPTIONAL_MENU_ACCESS:
            menu = self.env.ref(menu_xmlid, raise_if_not_found=False)
            if not menu:
                skipped.append(menu_xmlid)
                continue

            vals = {}
            if 'active' in spec:
                vals['active'] = spec['active']
            if 'groups' in spec:
                group_ids = []
                for group_xmlid in spec['groups']:
                    group = self.env.ref(group_xmlid, raise_if_not_found=False)
                    if group:
                        group_ids.append(group.id)
                    else:
                        # The menu exists but one of the groups meant to see it
                        # does not. Worth saying out loud: silently writing the
                        # shorter list would quietly widen or narrow access.
                        _logger.warning(
                            "ft_homepage: group %s not found while restricting "
                            "menu %s — it will not be granted access.",
                            group_xmlid, menu_xmlid,
                        )
                vals['group_ids'] = [(6, 0, group_ids)]

            menu.sudo().write(vals)
            applied.append(menu_xmlid)

        _logger.info(
            "ft_homepage: Homepage access applied to %s optional app menu(s): %s",
            len(applied), ", ".join(applied) or "none",
        )
        if skipped:
            _logger.info(
                "ft_homepage: %s optional app menu(s) not present on this "
                "database, nothing to restrict: %s",
                len(skipped), ", ".join(skipped),
            )
