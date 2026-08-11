/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useFileViewer } from "@web/core/file_viewer/file_viewer_hook";
import { FileModel } from "@web/core/file_viewer/file_model";
import {
    Many2ManyBinaryField,
    many2ManyBinaryField,
} from "@web/views/fields/many2many_binary/many2many_binary_field";

/**
 * Evidence attachments field.
 *
 * Identical to the stock many2many_binary widget — same tiles, same upload and
 * delete — with one addition: clicking an attachment opens Odoo's built-in file
 * viewer (images, PDF, video, text) in a modal instead of forcing a download.
 * File types the viewer can't render still fall back to a plain download, so
 * nothing that worked before stops working.
 */
export class EvidenceAttachmentsField extends Many2ManyBinaryField {
    static template = "qa_testapp.EvidenceAttachmentsField";

    setup() {
        super.setup();
        this.fileViewer = useFileViewer();
    }

    _toFileModel(file) {
        const model = new FileModel();
        Object.assign(model, {
            id: file.id,
            name: file.name,
            filename: file.name,
            mimetype: file.mimetype,
            type: "binary",
        });
        return model;
    }

    /** Preview when the viewer supports the type; otherwise download. */
    onFileClick(file) {
        const models = this.files.map((f) => this._toFileModel(f));
        const target = models.find((m) => m.id === file.id);
        if (target && target.isViewable) {
            this.fileViewer.open(target, models);
        } else {
            window.open("/web/content/" + file.id + "?download=true", "_blank");
        }
    }
}

export const evidenceAttachmentsField = {
    ...many2ManyBinaryField,
    component: EvidenceAttachmentsField,
};

registry.category("fields").add("qa_evidence_files", evidenceAttachmentsField);
