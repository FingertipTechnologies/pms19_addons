/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { ControlPanel } from "@web/search/control_panel/control_panel";

const PROJECT_PLANNER_TAG = "ft_pms_project_planner";
const TASK_PLANNER_TAG = "ft_pms_task_planner";

/** Window actions (by xml id) that show the "Project Status" button. */
const PMS_PROJECT_ACTIONS = new Set([
    "project.open_view_project_all",
    "project.open_view_project_all_group_stage",
]);
/** Window actions (by xml id) that show the "Task Planner" button. */
const PMS_TASK_ACTIONS = new Set(["project.action_view_all_task"]);

/**
 * Adds planner icon buttons to the control panel navigation group, right
 * before the view switcher, in every view of the targeted actions. The
 * target is identified by env.config.actionXmlId; nothing shows in dialogs.
 */
patch(ControlPanel.prototype, {
    get pmsActionXmlId() {
        if (this.env.inDialog) {
            return false;
        }
        return this.env.config?.actionXmlId || false;
    },

    get pmsShowProjectPlanner() {
        return PMS_PROJECT_ACTIONS.has(this.pmsActionXmlId);
    },

    get pmsShowTaskPlanner() {
        return PMS_TASK_ACTIONS.has(this.pmsActionXmlId);
    },

    get pmsPlannerButtons() {
        const buttons = [];
        if (this.pmsShowProjectPlanner) {
            buttons.push({
                key: "project_planner",
                name: _t("Project Status"),
                icon: "fa-th",
                onClick: () => this.pmsOpenProjectPlanner(),
            });
        }
        if (this.pmsShowTaskPlanner) {
            buttons.push({
                key: "task_planner",
                name: _t("Task Planner"),
                icon: "fa-columns",
                onClick: () => this.pmsOpenTaskPlanner(),
            });
        }
        return buttons;
    },

    /**
     * Project id when the search holds exactly one Project facet value that
     * is a record id (picked from the autocomplete); false otherwise.
     */
    pmsGetSearchedProjectId() {
        const searchModel = this.env.searchModel;
        if (!searchModel?.query || !searchModel.searchItems) {
            return false;
        }
        const values = [];
        for (const queryElem of searchModel.query) {
            const searchItem = searchModel.searchItems[queryElem.searchItemId];
            if (searchItem?.type === "field" && searchItem.fieldName === "project_id") {
                values.push(queryElem.autocompleteValue?.value);
            }
        }
        if (values.length === 1 && Number.isInteger(values[0])) {
            return values[0];
        }
        return false;
    },

    pmsOpenProjectPlanner() {
        this.env.services.action.doAction({
            type: "ir.actions.client",
            tag: PROJECT_PLANNER_TAG,
            name: _t("Project Status"),
        });
    },

    pmsOpenTaskPlanner() {
        const projectId = this.pmsGetSearchedProjectId();
        const params = projectId ? { project_id: projectId } : {};
        this.env.services.action.doAction({
            type: "ir.actions.client",
            tag: TASK_PLANNER_TAG,
            name: _t("Task Planner"),
            params,
            context: { ...params },
        });
    },
});
