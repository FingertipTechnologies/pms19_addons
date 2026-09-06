"""Keep previously installed tracking data when its models move to an addon."""

from odoo.addons.bt_project_customization.migration_helpers import (
    NEW_MODULE,
    move_project_tracking_metadata,
)


def migrate(cr, version):
    if not version:
        return

    cr.execute("SELECT to_regclass('ft_project_module')")
    had_tracking = bool(cr.fetchone()[0])
    moved = move_project_tracking_metadata(cr)
    if not had_tracking and not moved:
        # A production restore that never had the feature stays opt-in.
        return

    # The normal loader will pick this up on its next dependency-graph pass.
    # The sole dependency (this module) is already being upgraded now.
    cr.execute("""
        UPDATE ir_module_module SET state = 'to install'
         WHERE name = %s AND state = 'uninstalled'
    """, (NEW_MODULE,))
    cr.execute('SELECT state FROM ir_module_module WHERE name = %s', (NEW_MODULE,))
    row = cr.fetchone()
    if not row or row[0] not in ('installed', 'to install', 'to upgrade'):
        raise RuntimeError(f'{NEW_MODULE} must be available to preserve project tracking.')

    if row[0] == 'to install':
        # During the old addon's view validation these fields are not loaded
        # yet. The new addon's XML reactivates the inherited view on install.
        cr.execute("""
            UPDATE ir_ui_view SET active = false
             WHERE id IN (
                 SELECT res_id FROM ir_model_data
                  WHERE module = %s AND name = 'view_project_form_ft_modules'
                    AND model = 'ir.ui.view'
             )
        """, (NEW_MODULE,))
