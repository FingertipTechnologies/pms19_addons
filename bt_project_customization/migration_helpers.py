"""Transfer the extracted tracking feature without deleting its existing data."""

OLD_MODULE = 'bt_project_customization'
NEW_MODULE = 'ft_project_module_tracking'
TRACKING_MODELS = ['ft.project.module', 'ft.stagewise.time']
TRACKING_XMLIDS = [
    'access_ft_stagewise_time',
    'access_ft_project_module',
    'access_ft_project_module_manager',
    'view_ft_project_module_tree',
    'view_ft_project_module_form',
    'action_ft_project_module',
    'menu_ft_project_module',
    'view_project_form_ft_modules',
]


def move_project_tracking_metadata(cr):
    """Move only this feature's XML IDs; leave tables and business rows intact.

    This runs before the old module's obsolete-data cleanup and also before
    installing the new addon. Repeating it is safe. Conflicting XML IDs abort
    the transaction rather than choosing a record and losing customizations.
    """
    cr.execute("""
        SELECT id, name, model, res_id
          FROM ir_model_data
         WHERE module = %s AND (
             name = ANY(%s)
             OR (model = 'ir.model' AND res_id IN (
                 SELECT id FROM ir_model WHERE model = ANY(%s)))
             OR (model = 'ir.model.fields' AND res_id IN (
                 SELECT id FROM ir_model_fields
                  WHERE model = ANY(%s)
                     OR (model = 'project.project'
                         AND name IN ('ft_module_ids', 'ft_stagewise_time_ids'))))
         )
    """, (OLD_MODULE, TRACKING_XMLIDS, TRACKING_MODELS, TRACKING_MODELS))
    records = cr.fetchall()
    for xmlid_id, name, model, res_id in records:
        cr.execute("""
            SELECT model, res_id FROM ir_model_data
             WHERE module = %s AND name = %s
        """, (NEW_MODULE, name))
        target = cr.fetchone()
        if target:
            if target != (model, res_id):
                raise RuntimeError(
                    f'Cannot move {OLD_MODULE}.{name}: '
                    f'{NEW_MODULE}.{name} points to a different record.'
                )
            cr.execute('DELETE FROM ir_model_data WHERE id = %s', (xmlid_id,))
        else:
            cr.execute('UPDATE ir_model_data SET module = %s WHERE id = %s',
                       (NEW_MODULE, xmlid_id))

    # Existing constraints/relations must belong to the new addon as well,
    # so uninstalling the former owner cannot clean up the transferred model.
    for table in ('ir_model_constraint', 'ir_model_relation'):
        cr.execute(f"""
            UPDATE {table}
               SET module = (SELECT id FROM ir_module_module WHERE name = %s)
             WHERE module = (SELECT id FROM ir_module_module WHERE name = %s)
               AND model IN (SELECT id FROM ir_model WHERE model = ANY(%s))
        """, (NEW_MODULE, OLD_MODULE, TRACKING_MODELS))
    return len(records)
