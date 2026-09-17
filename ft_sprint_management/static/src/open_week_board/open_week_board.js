/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

/**
 * "Open Full Board" on the project's Tasks tab, as a widget rather than an
 * object button.
 *
 * A `type="object"` button saves the record before it runs, and a save checks
 * every required field on the form first — including core's hidden Closed
 * Date (`date`), which project.edit_project requires whenever the Start Date
 * is set. Plenty of projects have a Start Date and no Closed Date yet, so the
 * button stopped on "invalid field" and the board never opened, although
 * opening a board changes nothing on the project.
 *
 * This asks the server for the same action and opens it without the save.
 * Moving a task on the board is still a write to that task, and goes through
 * every rule it always did. Unsaved edits on the project are still saved on
 * the way out, as leaving any form does.
 */
export class OpenWeekBoard extends Component {
    static template = "ft_sprint_management.OpenWeekBoard";
    static props = { ...standardWidgetProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
    }

    get disabled() {
        return !this.props.record.resId;
    }

    async onClick() {
        const { record } = this.props;
        if (!record.resId) {
            return;
        }
        const action = await this.orm.call(
            record.resModel,
            "action_view_week_board",
            [[record.resId]],
            { context: record.context }
        );
        await this.action.doAction(action);
    }
}

registry.category("view_widgets").add("ft_open_week_board", {
    component: OpenWeekBoard,
});
