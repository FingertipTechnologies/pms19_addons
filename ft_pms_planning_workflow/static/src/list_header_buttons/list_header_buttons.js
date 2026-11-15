/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { ListController } from "@web/views/list/list_controller";

/**
 * List header buttons are evaluated in the list's own context, which knows
 * nothing about the selected rows. For task lists carrying the AMC approval
 * columns, ft_project_type and pwf_amc_approval are summarised over the
 * selection so the Approve / Reject / Reset Approval buttons can hide when
 * they would do nothing:
 *   ft_project_type   'amc' when at least one selected task is an AMC task
 *   pwf_amc_approval  'approved' / 'rejected' when every selected AMC task
 *                     is, false when none has an approval, 'mixed' otherwise
 *
 * Other addons add their own summaries by patching
 * ftListHeaderSelectionContext(ctx, selection, fields) - it receives the
 * selected records (with data), the list's fields and the context to fill.
 */
patch(ListController.prototype, {
    evalViewModifier(modifier) {
        const root = this.model.root;
        const fields = root.fields || {};
        if (!("pwf_amc_approval" in fields && "ft_project_type" in fields)) {
            return super.evalViewModifier(modifier);
        }
        const ctx = { ...root.evalContext };
        const selection = (root.selection || []).filter((r) => r.data);
        this.ftListHeaderSelectionContext(ctx, selection, fields);
        return evaluateBooleanExpr(modifier, ctx);
    },

    ftListHeaderSelectionContext(ctx, selection, fields) {
        // Buttons are evaluated even with nothing selected: default to
        // "no AMC task selected" so the names always exist.
        ctx.ft_project_type = false;
        ctx.pwf_amc_approval = false;
        if (selection.length) {
            const amc = selection.filter((r) => r.data.ft_project_type === "amc");
            const states = amc.map((r) => r.data.pwf_amc_approval || false);
            ctx.ft_project_type = amc.length ? "amc" : false;
            if (states.every((s) => s === "approved")) {
                ctx.pwf_amc_approval = "approved";
            } else if (states.every((s) => s === "rejected")) {
                ctx.pwf_amc_approval = "rejected";
            } else if (states.every((s) => !s)) {
                ctx.pwf_amc_approval = false;
            } else {
                ctx.pwf_amc_approval = "mixed";
            }
        }
    },
});
