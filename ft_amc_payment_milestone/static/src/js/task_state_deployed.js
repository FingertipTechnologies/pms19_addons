/** @odoo-module **/
/*
 * "Deployed" (state 1_deployed, ft_amc_payment_milestone) in the task Status
 * widget.
 *
 * project's ProjectTaskStateSelection keeps three hard-coded maps keyed by
 * state (icon, icon colour, pill button class) and a hard-coded list of the
 * states its dropdown offers. The maps get the new value so a deployed task
 * shows a cloud-upload icon in success green (kanban, list, calendar,
 * activity and the form's pill, and the stage+state widget which reuses
 * this component). The dropdown list is deliberately NOT extended: the
 * Mark Deployed / Undo Deployed buttons own that transition, with their
 * rights check, and the server refuses a direct write of 1_deployed.
 *
 * The label getter is patched because the component computes the label
 * from its own (shortened) option list, which would render an empty label
 * for a value that is not in it; the field's full selection has it.
 */
import { patch } from "@web/core/utils/patch";
import { formatSelection } from "@web/views/fields/formatters";
import { ProjectTaskStateSelection } from "@project/components/project_task_state_selection/project_task_state_selection";

export const FT_DEPLOYED_STATE = "1_deployed";

patch(ProjectTaskStateSelection.prototype, {
    setup() {
        super.setup();
        this.icons[FT_DEPLOYED_STATE] = "fa fa-lg fa-cloud-upload";
        this.colorIcons[FT_DEPLOYED_STATE] = "text-success";
        this.colorButton[FT_DEPLOYED_STATE] = "btn-outline-success";
    },

    get label() {
        if (this.currentValue === FT_DEPLOYED_STATE) {
            return formatSelection(FT_DEPLOYED_STATE, {
                selection: this.props.record.fields[this.props.name].selection,
            });
        }
        return super.label;
    },
});
