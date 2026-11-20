# -*- coding: utf-8 -*-
"""Small shims so the same source loads on Odoo 19 (declarative
``models.Constraint`` / ``models.Index``) and on 17/18 (``_sql_constraints``).

Everything that differs between versions is isolated here and listed in
docs/LIMITATIONS.md under "APIs to verify against your Odoo 19 checkout".
"""
from odoo import models

HAS_CONSTRAINT = hasattr(models, 'Constraint')
HAS_INDEX = hasattr(models, 'Index')


def ensure_index(cr, name, table, columns):
    """Create a btree index if missing.  Only literals from this codebase are
    ever interpolated (never user input)."""
    cr.execute('CREATE INDEX IF NOT EXISTS %s ON %s (%s)' % (name, table, ', '.join(columns)))
