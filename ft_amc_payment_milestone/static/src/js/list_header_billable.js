/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ListController } from "@web/views/list/list_controller";
import "@ft_pms_planning_workflow/list_header_buttons/list_header_buttons";

/**
 * Selection summary for the Mark Billable / Undo Billable list header
 * buttons (see ft_pms_planning_workflow's ftListHeaderSelectionContext):
 *   ft_billable_selection  'all'   every selected AMC task is already Billable
 *                          'none'  no selected AMC task is Billable
 *                          'mixed' some are
 * so Mark Billable hides on already-billable rows (only Undo stays) and Undo
 * hides when nothing selected is billable.
 */
patch(ListController.prototype, {
    ftListHeaderSelectionContext(ctx, selection, fields) {
        super.ftListHeaderSelectionContext(ctx, selection, fields);
        ctx.ft_billable_selection = "none";
        if (!("ft_deployed" in fields)) {
            return;
        }
        const amc = selection.filter((r) => r.data.ft_project_type === "amc");
        if (!amc.length) {
            return;
        }
        const billable = amc.filter((r) => r.data.ft_deployed).length;
        if (billable === amc.length) {
            ctx.ft_billable_selection = "all";
        } else if (billable > 0) {
            ctx.ft_billable_selection = "mixed";
        }
    },
});
