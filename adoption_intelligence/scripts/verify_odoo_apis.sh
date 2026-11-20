#!/usr/bin/env bash
# Confirms, against YOUR Odoo 19 checkout, every framework API this module relies on
# and that could not be verified while writing it.  Run it BEFORE installing:
#     bash verify_odoo_apis.sh ~/Documents/odoo_dinesh/odoo
# Every line should print FOUND.  A MISSING line names the exact file to adjust
# (see docs/LIMITATIONS.md section 2).
ODOO="${1:-$HOME/Documents/odoo_dinesh/odoo}"
chk() { # description, pattern, path
  if grep -rqE "$2" "$ODOO/$3" 2>/dev/null; then echo "FOUND    $1"; else echo "MISSING  $1   (pattern: $2 in $3)"; fi
}
chk "res.users._update_last_login (login hook)"          "def _update_last_login"                      odoo/addons/base/models/res_users.py
chk "Cursor.savepoint(flush=...)"                        "def savepoint\(self, flush"                   odoo/sql_db.py
chk "cr.precommit.data (per-transaction state)"          "precommit"                                    odoo/sql_db.py
chk "Model._read_group(domain, groupby, aggregates)"     "def _read_group\(self, domain, groupby"       odoo/orm/models.py
chk "records.check_access('read')"                       "def check_access\(self"                       odoo/orm/models.py
chk "read(fields, load=...)"                             "def read\(self, fields.*load"                 odoo/orm/models.py
chk "Field.inherited attribute"                          "inherited"                                    odoo/orm/fields.py
chk "models.Constraint / models.Index (declarative)"     "class Constraint|class Index"                 odoo/orm
chk "registry.clear_cache()"                             "def clear_cache"                              odoo/orm/registry.py
chk "registry._init flag (module loading)"               "_init"                                        odoo/orm/registry.py
chk "registry.in_test_mode()"                            "def in_test_mode"                             odoo/orm/registry.py
chk "fields.Datetime.context_timestamp"                  "def context_timestamp"                        odoo/orm/fields_temporal.py
chk "res.groups implied_ids"                             "implied_ids"                                  odoo/addons/base/models/res_users.py
chk "res.users group field name (group_ids / groups_id)" "group_ids|groups_id"                          odoo/addons/base/models/res_users.py
chk "ir.cron fields (no numbercall expected)"            "interval_type"                                odoo/addons/base/models/ir_cron.py
chk "web: ORM class (patched by the tracker)"            "export class ORM"                             addons/web/static/src/core/orm_service.js
chk "web: patch util"                                    "export function patch"                        addons/web/static/src/core/utils/patch.js
chk "web: action service currentController"              "currentController"                            addons/web/static/src/webclient/actions/action_service.js
chk "web: router module"                                 "export const router"                          addons/web/static/src/core/browser/router.js
chk "web: orm.silent"                                    "get silent"                                   addons/web/static/src/core/orm_service.js
chk "http: /json/ API prefix"                            "/json/"                                       odoo/http.py
echo
echo "Also confirm manually after install:  odoo-bin ... --test-enable --test-tags /adoption_intelligence"
