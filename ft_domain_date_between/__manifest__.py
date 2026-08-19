# -*- coding: utf-8 -*-
{
    "name": "FT Domain Editor - Date \"between\" Operator",
    "version": "19.0.1.0.0",
    "category": "Technical",
    "summary": "Restore an explicit \"between\" operator for date fields in the "
               "custom filter / domain editor.",
    "description": """
FT Domain Editor - Date "between" Operator
==========================================
Odoo 19 dropped ``between`` from the operator list of date and datetime fields
in the domain editor (Search -> Add Custom Filter). The capability itself did
not disappear - it moved into the *value* dropdown of the ``in range`` ("is
in") operator, as its "Custom range" entry - but nobody finds it there, and
numeric fields still show a plain "between", which makes the difference look
like a bug.

This module puts "between" back in the operator dropdown for date and datetime
fields, alongside "is in".

Two patches are needed, and both are required - the first one alone does not
work:

* ``DomainSelector`` gains ``between`` in the operator list it offers for
  date/datetime fields.
* the ``tree_processor`` service rewrites ``in range`` + "custom range" back
  into ``between`` when it rebuilds the tree from a domain. Without this the
  editor re-derives its tree from the domain string after every keystroke and
  immediately flips the operator back to "is in", because both forms compile
  to the very same domain and ``introduceInRangeOperators`` claims it first.

The relative smart-date presets (Today, Last 7 days, Month to date, ...) are
untouched and stay under "is in": they compile to a *strict* between
(``>=`` / ``<``) which this module does not intercept.

Uninstall to restore the stock behaviour.
""",
    "author": "Fingertip",
    "license": "LGPL-3",
    "depends": [
        "web",
    ],
    "assets": {
        "web.assets_backend": [
            "ft_domain_date_between/static/src/js/date_between_operator.js",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
