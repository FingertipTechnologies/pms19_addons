/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { ListController } from "@web/views/list/list_controller";

/**
 * Expense Claims list: the "Approve Claims" / "Mark Claims as Paid" header
 * buttons are evaluated in the list's own eval context, which knows nothing
 * about the selected rows. For employee.expense.claim lists two booleans are
 * summarised over the selection so each button hides when it would do
 * nothing on the selected claims:
 *
 *   ft_claim_can_approve  at least one selected claim can still be approved
 *   ft_claim_can_pay      at least one selected claim can still be paid
 * (each row's own flag is the computed field of the same name, so the rules
 * live once, in employee.expense.claim._compute_ft_claim_can).
 *
 * Both are false when nothing is selected. Lists of any other model fall
 * through to the standard evaluation, so this coexists with other addons'
 * evalViewModifier patches (they do the same for lists that are not theirs).
 */
patch(ListController.prototype, {
    evalViewModifier(modifier) {
        const root = this.model.root;
        const fields = root.fields || {};
        if (root.resModel !== "employee.expense.claim" || !("ft_claim_can_approve" in fields)) {
            return super.evalViewModifier(modifier);
        }
        const selection = (root.selection || []).filter((r) => r.data);
        const ctx = { ...root.evalContext };
        ctx.ft_claim_can_approve = selection.some((r) => r.data.ft_claim_can_approve);
        ctx.ft_claim_can_pay = selection.some((r) => r.data.ft_claim_can_pay);
        return evaluateBooleanExpr(modifier, ctx);
    },
});
