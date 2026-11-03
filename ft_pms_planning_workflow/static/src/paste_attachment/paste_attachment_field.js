import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useFileUploader } from "@web/core/utils/files";
import {
    Many2ManyBinaryField,
    many2ManyBinaryField,
} from "@web/views/fields/many2many_binary/many2many_binary_field";

/**
 * many2many_binary with a small "paste" button next to the paperclip: a
 * screenshot copied to the clipboard is uploaded as an attachment, either
 * with the button or with Ctrl+V while the field has the focus.
 */
export class PasteAttachmentField extends Many2ManyBinaryField {
    static template = "ft_pms_planning_workflow.PasteAttachmentField";

    setup() {
        super.setup();
        this.uploadFiles = useFileUploader();
    }

    _imageFiles(items) {
        const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
        return items.map((blob, i) => {
            const ext = (blob.type.split("/")[1] || "png").replace("jpeg", "jpg");
            return new File([blob], `screenshot-${stamp}${i ? "-" + i : ""}.${ext}`, {
                type: blob.type,
            });
        });
    }

    async _upload(blobs) {
        if (!blobs.length) {
            this.notification.add(_t("The clipboard holds no image to paste."), {
                type: "warning",
            });
            return;
        }
        const params = {
            csrf_token: odoo.csrf_token,
            ufile: this._imageFiles(blobs),
            model: this.props.record.resModel,
            id: this.props.record.resId || 0,
        };
        const files = await this.uploadFiles("/web/binary/upload_attachment", params);
        await this.onFileUploaded(files);
    }

    async onPasteClick() {
        if (!navigator.clipboard || !navigator.clipboard.read) {
            this.notification.add(_t("Click the field and press Ctrl+V to paste."), {
                type: "info",
            });
            return;
        }
        let blobs = [];
        try {
            for (const item of await navigator.clipboard.read()) {
                const type = item.types.find((t) => t.startsWith("image/"));
                if (type) {
                    blobs.push(await item.getType(type));
                }
            }
        } catch {
            this.notification.add(_t("Clipboard access was refused: press Ctrl+V instead."), {
                type: "info",
            });
            return;
        }
        await this._upload(blobs);
    }

    async onPaste(ev) {
        if (this.props.readonly) {
            return;
        }
        const blobs = [...(ev.clipboardData?.items || [])]
            .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
            .map((item) => item.getAsFile());
        if (blobs.length) {
            ev.preventDefault();
            await this._upload(blobs);
        }
    }
}

registry.category("fields").add("many2many_binary_paste", {
    ...many2ManyBinaryField,
    component: PasteAttachmentField,
});
