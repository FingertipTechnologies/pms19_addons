# -*- coding: utf-8 -*-
from . import services
from . import models
from . import wizard
from . import controllers


def post_init_hook(env):
    """Seed the recommended models/fields that are installed in THIS database
    (never references a model that is not there) and create the singleton
    settings record."""
    env['adoption.settings']._get()
    env['adoption.tracking.config']._seed_defaults()
