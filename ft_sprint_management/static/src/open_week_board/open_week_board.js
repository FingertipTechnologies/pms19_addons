/** @odoo-module **/

import { Component, onMounted, onPatched, onWillUnmount, useRef } from "@odoo/owl";
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

        // The strip this button sits in is sticky, and it has to come to rest
        // UNDER the tab bar rather than at the top of the scrolling area —
        // see .o_week_board_toolbar in week_task_board.scss for the whole
        // stack. The tab bar's height is not a constant (the names wrap, the
        // bar carries a scrollbar of its own on a narrow screen, the browser
        // zooms), so it is measured here and published as a CSS variable, the
        // way bt_project_customization publishes the status bar's height for
        // the tab bar itself.
        this.headersRef = useRef("root");
        this.observedHeaders = null;
        this.headersObserver = null;
        onMounted(() => this.trackTabsHeight());
        // The notebook's header node is replaced by a re-render — another
        // project through the pager, a stage change — so the new one has to be
        // picked up.
        onPatched(() => this.trackTabsHeight());
        onWillUnmount(() => this.headersObserver?.disconnect());
    }

    /** Publish the tab bar's height on the sticky strip that has to clear it. */
    trackTabsHeight() {
        const toolbar = this.headersRef.el?.closest(".o_week_board_toolbar");
        const headers = toolbar
            ?.closest(".o_notebook")
            ?.querySelector(":scope > .o_notebook_headers");
        if (!toolbar || !headers) {
            return;
        }
        if (headers === this.observedHeaders) {
            return;
        }
        this.headersObserver?.disconnect();
        this.observedHeaders = headers;
        this.headersObserver = new ResizeObserver(() => {
            toolbar.style.setProperty(
                "--ft-week-board-tabs-height",
                `${headers.getBoundingClientRect().height}px`
            );
        });
        this.headersObserver.observe(headers);
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
