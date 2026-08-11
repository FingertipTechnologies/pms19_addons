# Copyright 2025 Tecnativa - Carlos Roca
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

# NOTE: In Odoo 18 this module monkey-patched ``Store.one_id`` to inject the
# partner ``gateway_channels`` into the Discuss store payload. Odoo 19 removed
# ``Store.one_id``; record serialization now goes through the model's
# ``_to_store`` / ``_to_store_defaults`` hooks. The equivalent injection now
# lives in ``res.partner._to_store_defaults`` (see models/res_partner.py).
