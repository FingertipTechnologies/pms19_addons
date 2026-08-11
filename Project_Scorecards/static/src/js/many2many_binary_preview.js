/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useFileViewer } from "@web/core/file_viewer/file_viewer_hook";
import { FileModel } from "@web/core/file_viewer/file_model";
import {
    Many2ManyBinaryField,
    many2ManyBinaryField,
} from "@web/views/fields/many2many_binary/many2many_binary_field";

/**
 * Drop-in replacement for the standard ``many2many_binary`` widget that lets
 * the user preview attachments (images, PDF, text, video) inline using Odoo's
 * built-in FileViewer instead of only being able to download them.
 */
export class Many2ManyBinaryPreviewField extends Many2ManyBinaryField {
    static template = "Project_Scorecards.Many2ManyBinaryPreviewField";

    setup() {
        super.setup();
        this.fileViewer = useFileViewer();
    }

    /** Build FileViewer-compatible models from the attachment records. */
    get viewerFiles() {
        return this.files.map((file) => {
            const model = new FileModel();
            model.id = file.id;
            model.name = file.name;
            model.mimetype = file.mimetype;
            return model;
        });
    }

    isViewable(file) {
        const model = new FileModel();
        model.id = file.id;
        model.name = file.name;
        model.mimetype = file.mimetype;
        return model.isViewable;
    }

    onPreview(file) {
        const files = this.viewerFiles;
        const target = files.find((f) => f.id === file.id);
        if (target) {
            this.fileViewer.open(target, files);
        }
    }
}

export const many2ManyBinaryPreviewField = {
    ...many2ManyBinaryField,
    component: Many2ManyBinaryPreviewField,
};

registry
    .category("fields")
    .add("many2many_binary_preview_sc", many2ManyBinaryPreviewField);
