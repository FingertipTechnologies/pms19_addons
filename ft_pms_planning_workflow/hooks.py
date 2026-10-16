from .planner_hooks import uninstall_hook as _planner_uninstall_hook


def uninstall_hook(env):
    """Hand the Projects list back to the stock view this addon replaced."""
    _planner_uninstall_hook(env)
