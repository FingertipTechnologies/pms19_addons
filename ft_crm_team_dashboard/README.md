# CRM Team Dashboard (v18 card)

Restores the Sales Team dashboard card that Odoo 18 showed and Odoo 19 removed.

## What Odoo 19 changed

The v19 card renders only the team name, the email alias, the unassigned lead
count and the salesperson avatar. The rest was deleted upstream, not hidden:

| Removed in v19 | Where it lived in v18 |
| --- | --- |
| `opportunities_count` / `_amount`, `opportunities_overdue_count` / `_amount` | `crm/models/crm_team.py` |
| `quotations_count` / `_amount`, `sales_to_invoice_count` | `sale/models/crm_team.py` |
| `dashboard_graph_data` and the whole `_graph_*` framework | `sales_team/models/crm_team.py` |
| The card layout using those fields | the `crm` and `sale` kanban inherits |

The two widgets are still shipped by standard v19 and are reused as-is:
`dashboard_graph` (in `web`) and `sales_team_progressbar` (in `sale`), so this
module carries no JavaScript.

## Differences from the v18 implementation

* Aggregations use `_read_group` instead of raw SQL: v19 dropped `_where_calc`
  and `_apply_ir_rules`, and `_read_group` applies record rules on its own.
* The graph groups per day and buckets into Monday-based ISO weeks in Python.
  v19's `:week` granularity truncates on the lang's first day of week (Sunday
  for `en_US`), which would have misaligned the bars with their v18-style
  `20-26 Jul` labels.
* Quotation amounts are converted per currency through `currency._convert`
  rather than v18's inline `currency_rate` division.
* No random "sample data" bars when a team has no activity - real zeros are
  shown. The kanban's own `sample="1"` empty state still covers the no-teams
  case.

## Verified against pms_19_migrated_db

Figures match the v18 production card exactly: 266 open opportunities
(79,735,551.00), 103 overdue (51,570,551.00), 2 quotations (40.00), and the
weekly bars 3 / 7 / 14 / 13 / 1.
