import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { RPCError } from "@web/core/network/rpc";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";
import { KanbanQuickCreateController } from "@web/views/kanban/kanban_record_quick_create";

/**
 * When the kanban quick create fails (a validation error on save), core opens
 * the full form with only the name filled, so everything typed in the small
 * card is lost. Carry every value entered in the card into the full form as
 * default_* keys, on a copy of the context so the next card stays clean.
 */
patch(KanbanQuickCreateController.prototype, {
    _ftQuickCreateDefaults() {
        const root = this.model.root;
        const defaults = {};
        try {
            const changes = root._getChanges(root._changes, { withReadonly: true });
            for (const [fname, value] of Object.entries(changes)) {
                const field = root.fields[fname];
                if (!field || value === false || value === undefined || field.type === "one2many") {
                    continue;
                }
                defaults[`default_${fname}`] =
                    field.type === "many2many" && Array.isArray(value)
                        ? value.flatMap((cmd) => (cmd[0] === 6 ? cmd[2] : cmd[0] === 4 ? [cmd[1]] : []))
                        : value;
            }
        } catch {
            // never block the fallback dialog itself
        }
        return defaults;
    },

    showFormDialogInError(e) {
        if (!(e instanceof RPCError)) {
            throw e;
        }
        const values = this.model.root.data;
        const context = {
            ...this.props.context,
            ...this._ftQuickCreateDefaults(),
            default_name: values.name || values.display_name,
        };
        this.addDialog(FormViewDialog, {
            resModel: this.props.resModel,
            context,
            title: _t("Create"),
            onRecordSaved: async (record) => {
                await this.props.onValidate(record.resId, "add");
                await this.model.load();
            },
        });
    },
});
