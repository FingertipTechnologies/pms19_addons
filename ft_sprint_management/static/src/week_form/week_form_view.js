/** @odoo-module **/

import { registry } from "@web/core/registry";
import { formView } from "@web/views/form/form_view";
import { FormController } from "@web/views/form/form_controller";

/**
 * The Week form, without New and without Save / Discard.
 *
 * A week is a position in the calendar and is created on its own the moment a
 * task is due in it, so there is nothing to create by hand (create="0" on the
 * arch removes New). Nor is there anything on it to save: its name and dates
 * follow from the Monday, and the one control somebody does change — the
 * Project selector above the board — is a view filter that is not stored.
 * Changing it still marks the record dirty, which is what brought up the Save
 * and Discard icons for a change that saves nothing.
 *
 * Only the icons go. Anything that does change on the record — a task added
 * under Assigned Tasks — is still saved the way every Odoo form saves on its
 * own: when the week is left through the breadcrumb, the pager or a button.
 */
export class WeekFormController extends FormController {
    static template = "ft_sprint_management.WeekFormView";
}

registry.category("views").add("ft_week_form", {
    ...formView,
    Controller: WeekFormController,
});
