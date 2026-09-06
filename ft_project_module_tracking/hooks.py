from odoo.addons.bt_project_customization.migration_helpers import (
    move_project_tracking_metadata,
)


def pre_init_hook(env):
    # Also supports installing this addon before upgrading its former owner.
    # Reuse existing XML IDs so views, permissions and model metadata keep IDs.
    move_project_tracking_metadata(env.cr)
    env['ir.model.data'].invalidate_model()
    env.registry.clear_cache()
