import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { SelectionField, selectionField } from "@web/views/fields/selection/selection_field";

/**
 * The Project Type selection, plus one behaviour on a record that does not
 * exist yet: choosing Implementation leaves for the full project form.
 *
 * Used only in the two places the Projects Kanban creates a project from —
 * core's "Create a Project" dialog (Name, Type, alias) and the column quick
 * create (Name, Type). Neither shows a date, and an Implementation project is
 * held to every date in the Dates section at creation
 * (project.project._ft_check_creation_dates), so a save from either could only
 * ever be refused for dates there was nowhere to type. Rather than let someone
 * fill the dialog in and find that out on Create, the choice of Implementation
 * itself hands over to the form the list view's New opens, name and type
 * carried across.
 *
 * AMC and General are not redirected. General has no date rule; AMC's two
 * (Start and End Date) are on the dialog itself, shown when AMC is picked.
 *
 * The full form is opened as a target "current" action, and the action
 * service closes every open dialog when it mounts one of those, so the
 * Create a Project dialog goes away by itself; its onClose is called with
 * noReload, so the Kanban underneath is not reloaded for a project that was
 * not created. The quick create simply stops being on screen when the Kanban
 * is replaced by the form. Nothing is saved on the way out — the record was
 * new and stays that way.
 */
export class ProjectTypeCreateField extends SelectionField {
    setup() {
        super.setup();
        this.action = useService("action");
        this.orm = useService("orm");
    }

    async onChange(value) {
        super.onChange(value);
        // Only ever on creation. On an existing project this is the ordinary
        // selection: a type change is a type change, not a reason to leave.
        if (value !== "implementation" || !this.props.record.isNew) {
            return;
        }
        const action = await this.orm.call(
            "project.project",
            "action_ft_open_full_create_form",
            [],
            {
                name: this.props.record.data.name || false,
                context: this.props.record.context,
            }
        );
        await this.action.doAction(action);
    }
}

export const projectTypeCreateField = {
    ...selectionField,
    component: ProjectTypeCreateField,
    supportedTypes: ["selection"],
};

registry.category("fields").add("ft_project_type_create", projectTypeCreateField);
