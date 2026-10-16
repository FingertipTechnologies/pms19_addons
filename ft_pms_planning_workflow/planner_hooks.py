def uninstall_hook(env):
    """Give the Projects menu its core list view back.

    The module points project.open_view_project_all_group_stage_tree_view at
    its own list view; that record belongs to `project`, so uninstalling this
    module would otherwise leave view_id empty (set null) instead of restoring
    the core grouped-by-stage list.
    """
    act_view = env.ref(
        'project.open_view_project_all_group_stage_tree_view',
        raise_if_not_found=False)
    core_view = env.ref(
        'project.project_list_view_group_stage', raise_if_not_found=False)
    if act_view and core_view:
        act_view.sudo().write({'view_id': core_view.id})
