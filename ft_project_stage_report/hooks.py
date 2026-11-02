import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Build the stage report lines of every Implementation project on
    install. The daily cron and the write triggers keep them fresh after."""
    lines = env['ft.project.stage.line']._rebuild_for_projects()
    _logger.info(
        "ft_project_stage_report: built %s stage line(s) on install.", len(lines))
