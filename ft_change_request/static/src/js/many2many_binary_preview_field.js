/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useFileViewer } from "@web/core/file_viewer/file_viewer_hook";
import { FileModel } from "@web/core/file_viewer/file_model";
import {
    Many2ManyBinaryField,
    many2ManyBinaryField,
} from "@web/views/fields/many2many_binary/many2many_binary_field";

/**
 * Same as the standard many2many_binary widget, but clicking an attachment
 * opens Odoo's native file-viewer popup (image / PDF / text / video) instead
 * of downloading it. Non-previewable types fall back to a download.
 */
export class Many2ManyBinaryPreviewField extends Many2ManyBinaryField {
    static template = "ft_change_request.Many2ManyBinaryPreviewField";

    setup() {
        super.setup();
        this.fileViewer = useFileViewer();
    }

    // Wrap each attachment in a FileModel so the viewer can resolve its
    // preview URL and decide whether it is viewable.
    get viewerFiles() {
        return this.files.map((f) => {
            const model = new FileModel();
            model.id = f.id;
            model.name = f.name;
            model.mimetype = f.mimetype;
            return model;
        });
    }

    onPreview(file) {
        const files = this.viewerFiles;
        const target = files.find((f) => f.id === file.id);
        if (target && target.isViewable) {
            this.fileViewer.open(target, files);
        } else {
            // e.g. XML / zip / office files the viewer can't render — download.
            window.location = this.getUrl(file.id);
        }
    }
}

export const many2ManyBinaryPreviewField = {
    ...many2ManyBinaryField,
    component: Many2ManyBinaryPreviewField,
};

registry.category("fields").add("many2many_binary_preview", many2ManyBinaryPreviewField);
