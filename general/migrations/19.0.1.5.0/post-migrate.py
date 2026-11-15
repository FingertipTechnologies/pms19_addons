"""19.0.1.5.0: an advance is adjusted by several claims.

employee.advance.related_expense_claim (Many2one, one claim) is replaced by
claim_ids (One2many on employee.expense.claim.advance_id). Carry the old
link over, then recompute the advances' adjusted / balance / status, which
are now computed from the claims' Advance Used.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'employee_advance' AND column_name = 'related_expense_claim'
    """)
    if cr.fetchone():
        cr.execute("""
            UPDATE employee_expense_claim c
               SET advance_id = a.id
              FROM employee_advance a
             WHERE a.related_expense_claim = c.id
               AND c.advance_id IS NULL
        """)
    env = api.Environment(cr, SUPERUSER_ID, {})
    Claim = env['employee.expense.claim']
    claims = Claim.search([])
    env.add_to_compute(Claim._fields['advance_used'], claims)
    Advance = env['employee.advance']
    advances = Advance.search([])
    for fname in ('adjusted_amount', 'balance_amount', 'status'):
        env.add_to_compute(Advance._fields[fname], advances)
    env.flush_all()
