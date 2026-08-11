import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { StatusBarField } from "@web/views/fields/statusbar/statusbar_field";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

// Which task stages count as completed, fetched once per session and shared by
// every status bar. Resolved server-side so the browser never carries its own
// copy of the stage list.
let finalStageIdsPromise = null;

function getFinalStageIds(orm) {
    if (!finalStageIdsPromise) {
        finalStageIdsPromise = orm
            .call("project.task", "ft_get_final_stage_ids", [])
            // Never let a failed lookup block the status bar; the server-side
            // timesheet guard is the real enforcement either way.
            .catch(() => []);
    }
    return finalStageIdsPromise;
}

/**
 * Ask before a task is moved into a Completed stage.
 *
 * Completing a task is not a cheap click here: it stamps the completion date
 * every delivery metric is measured against, and it locks the task for
 * timesheets. Coming back out of it is counted as rework. A stray click on the
 * status bar therefore costs someone a reopen on their Rework Rate, which is
 * worth one question.
 *
 * "Completed" is decided by the server's final-stage list, NOT by the item's
 * own isFolded flag. That flag is what the check used to read, and it is False
 * on every stage in this database — the Completed stage was never ticked
 * "Folded in Kanban" — so the dialog never appeared even though the code for it
 * had been shipped and loaded all along.
 *
 * Patched on StatusBarField rather than on the task form: the task form uses
 * `statusbar_duration`, whose component extends StatusBarField without
 * overriding selectItem, so the prototype patch reaches both. The guard on
 * resModel keeps every other model's status bar untouched.
 *
 * Scope: this covers the status bar on the task form. Dragging a card between
 * kanban columns does not route through this component and is not intercepted
 * — the server-side timesheet block is what holds in every case.
 */
patch(StatusBarField.prototype, {
    async selectItem(item) {
        const record = this.props.record;
        if (record?.resModel !== "project.task" || item.isSelected) {
            return super.selectItem(...arguments);
        }

        // `value` carries the stage id on a many2one status bar; `id` is not a
        // key of these items.
        const finalIds = await getFinalStageIds(this.env.services.orm);
        const movingToCompleted = item.isFolded || finalIds.includes(item.value);

        if (!movingToCompleted) {
            return super.selectItem(...arguments);
        }

        return new Promise((resolve) => {
            this.env.services.dialog.add(ConfirmationDialog, {
                title: _t("Complete this task?"),
                // Plain text, not markup: keep it one flowing paragraph, since
                // newlines would not render as breaks here.
                body: _t(
                    "Are you sure the task is completed? Once completed, no more " +
                        "timesheets can be logged against it. If further work turns out " +
                        "to be needed, moving it back to Working counts as rework and " +
                        "affects the Rework Rate."
                ),
                confirmLabel: _t("Yes, it is completed"),
                cancelLabel: _t("Not yet"),
                confirm: async () => {
                    await super.selectItem(item);
                    resolve();
                },
                // Dismissing leaves the stage untouched, which is the point.
                cancel: () => resolve(),
            });
        });
    },
});
