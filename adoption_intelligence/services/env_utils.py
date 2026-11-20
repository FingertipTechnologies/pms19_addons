# -*- coding: utf-8 -*-
"""Small, duck-typed helpers about the Odoo environment (no Odoo imports, unit tested)."""


def in_test_mode(env):
    """True while Odoo runs its test suite (so long jobs must not ``cr.commit()``).

    Odoo 17/18 expose ``registry.in_test_mode()``; Odoo 19 does not (``AttributeError``),
    it has a ``test_mode`` flag.  Ask in the order of preference and never raise.
    """
    registry = env.registry
    probe = getattr(registry, 'in_test_mode', None)
    if callable(probe):
        try:
            return bool(probe())
        except Exception:  # noqa: BLE001 - fall through to the attribute checks
            pass
    return bool(getattr(registry, 'test_mode', False) or getattr(registry, 'test_cr', None) is not None)
