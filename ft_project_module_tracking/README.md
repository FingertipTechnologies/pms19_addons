# Project Modules and Stage-wise Time

Technical name: `ft_project_module_tracking`.

This optional addon owns the `ft.project.module` model, the
`ft.stagewise.time` SQL report, the project's `ft_module_ids` and
`ft_stagewise_time_ids` fields, their views, menu, action and access rules.
These definitions previously lived in `bt_project_customization`.

The addon depends on `bt_project_customization`, which still owns the
timesheet `project_status` snapshot field and its recording logic. Existing
addons do not depend on this addon, and it is not automatically installed on
a database that has never had this feature.

## Testing a fresh production restore

1. Deploy both the changed `bt_project_customization` folder and this addon.
2. Restart the local Odoo process so it loads the changed Python imports.
3. Restore/select the production backup and use **Update Apps List**.
4. Upgrade **Project Customization** (`bt_project_customization`) and the
   other changed installed addons. These still contain schema changes.
5. Remove the default **Apps** filter, search for the technical name
   `ft_project_module_tracking`, and install **Project Modules and Stage-wise
   Time**. It is an optional technical addon, not a standalone application.
6. Check **Project → Configuration → Project Modules** and the **Stage-wise
   Time** tab on a project. Refresh the Apps list again.

Before step 5, this addon's models are absent from the registry. Therefore
changes to `ir.module.module.category_id` during an Apps refresh cannot
trigger a lookup of a missing `ft_project_module` table.

## Databases that already have the feature

Upgrade `bt_project_customization` to `19.0.1.10.0`. Its pre-migration detects
the previous tracking table or metadata, moves the feature's XML IDs to this
addon, and schedules this addon for installation in the same upgrade. The
existing model, field, view, menu, action and access-rule record IDs are
retained; the `ft_project_module` table and business rows are not replaced.
The stage-time report continues to use the existing timesheets.

The install hook also transfers metadata if the new addon is installed before
upgrading the former owner. The transfer is idempotent and stops with an
explicit error if a target XML ID identifies a different record.

Do not remove this addon from the deployed files while upgrading the former
owner. Do not uninstall the former owner to perform the split.

## Scope

This addresses the Apps-list error caused by the premature loading of these
two models. It does not remove the need to upgrade the other changed addons
or guarantee production deployment without a maintenance window.

## Validation performed

Tested on temporary copies of the local production backup and the already
upgraded local database:

- Apps refresh before upgrading, with both extracted models absent.
- The same `button_immediate_upgrade` method used by the browser, followed
  by explicit installation of the optional addon on the production restore.
- Project-form validation, reads from both models and another Apps refresh.
- Automatic installation during the former owner's upgrade on the existing
  database, preserving a sample business row and all 37 checked XML ID targets.
- Repeating the metadata transfer without further changes.

The restored databases still reported existing required-field and contact-view
validation issues unrelated to this split; those remain outside this change.
