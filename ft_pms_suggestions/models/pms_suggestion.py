# -*- coding: utf-8 -*-
from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import AccessError

# Bus notification type. The JS listener in
# static/src/js/suggestion_notification.js subscribes to this exact string, so
# the two have to be changed together.
BUS_NOTIFICATION_TYPE = "ft_pms_suggestions.new_suggestion"

# Comma-separated logins notified on top of the administrators. Held in a
# system parameter so the recipient list can be edited from Settings without a
# code change or a module upgrade.
NOTIFY_LOGINS_PARAM = "ft_pms_suggestions.notify_logins"


class PmsSuggestion(models.Model):
    _name = "pms.suggestion"
    _description = "PMS Suggestion"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"
    _rec_name = "name"

    name = fields.Char(
        string="ID",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: "New",
        help="Auto-generated suggestion number.",
    )
    title = fields.Char(required=True, tracking=True)
    category_id = fields.Many2one(
        "pms.suggestion.category",
        string="Module / Area",
        required=True,
        tracking=True,
        help="Which PMS module/area this suggestion relates to.",
    )
    description = fields.Html(
        string="Description",
        sanitize_attributes=False,
        help="Rich text — you can paste images directly here. Use the "
        "chatter's paperclip icon below to attach files as well.",
    )

    state = fields.Selection(
        [
            ("new", "Suggestion"),
            ("approved", "Approved"),
            ("implemented", "Implemented"),
        ],
        default="new",
        required=True,
        tracking=True,
        copy=False,
    )

    suggested_by_id = fields.Many2one(
        "res.users",
        string="Suggested By",
        default=lambda self: self.env.user,
        readonly=True,
        tracking=True,
    )

    # Once state != 'new', the record is read-only for everyone. An Admin
    # can flip this to temporarily unlock it for editing.
    admin_unlocked = fields.Boolean(
        string="Unlocked for Editing",
        copy=False,
        help="Admins can toggle this to edit a suggestion that has already "
        "been approved/implemented.",
    )
    is_admin = fields.Boolean(
        compute="_compute_is_admin",
        help="Technical field used by the view to show/hide admin-only "
        "controls.",
    )

    @api.depends_context("uid")
    def _compute_is_admin(self):
        is_admin = self.env.user.has_group("base.group_system")
        for rec in self:
            rec.is_admin = is_admin

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "pms.suggestion"
                ) or "New"
        records = super().create(vals_list)
        records._log_creation_note()
        records._notify_new_suggestion()
        return records

    def write(self, vals):
        # Defense in depth: even if someone bypasses the view's readonly
        # attrs (e.g. via direct RPC/import), block edits to a
        # locked/approved suggestion for non-admins, unless it has been
        # explicitly unlocked.
        protected_fields = set(vals.keys()) - {"admin_unlocked", "message_follower_ids", "message_ids", "activity_ids"}
        if protected_fields and not self.env.user.has_group("base.group_system"):
            for rec in self:
                if rec.state != "new" and not rec.admin_unlocked:
                    raise AccessError(
                        "This suggestion has been Approved/Implemented and "
                        "is read-only. Ask an Admin to unlock it if it "
                        "needs changes."
                    )
        return super().write(vals)

    def _check_is_admin(self):
        if not self.env.user.has_group("base.group_system"):
            raise AccessError("Only Admins can perform this action.")

    def action_approve(self):
        self._check_is_admin()
        self.write({"state": "approved", "admin_unlocked": False})

    def action_implement(self):
        self._check_is_admin()
        self.write({"state": "implemented", "admin_unlocked": False})

    def action_reset_to_suggestion(self):
        self._check_is_admin()
        self.write({"state": "new", "admin_unlocked": False})

    def action_unlock(self):
        self._check_is_admin()
        self.admin_unlocked = True

    def action_lock(self):
        self._check_is_admin()
        self.admin_unlocked = False

    # ------------------------------------------------------------------
    # Notification
    #
    # Delivery is over the Odoo bus, never by email. Nothing here touches
    # mail.mail or an outgoing mail server: the popup is pushed straight to
    # the recipients' open browser tabs. Someone who is not logged in simply
    # misses it and picks the suggestion up from the Suggestions menu
    # filtered on state = 'new'.
    # ------------------------------------------------------------------

    def _notification_recipient_users(self):
        """Users who should receive the new-suggestion popup.

        Administrators, plus whoever is named in the notify-logins system
        parameter. Recipients are resolved by login rather than by a name
        search: a login is unique and stable, so renaming somebody — or a
        second person sharing their first name — cannot silently redirect the
        notification or send it twice.
        """
        Users = self.env["res.users"].sudo()
        recipients = Users.search(
            [("group_ids", "=", self.env.ref("base.group_system").id)]
        )
        raw = self.env["ir.config_parameter"].sudo().get_param(
            NOTIFY_LOGINS_PARAM, default=""
        )
        logins = [login.strip() for login in raw.split(",") if login.strip()]
        if logins:
            # `|` on recordsets de-duplicates, so somebody who is both an
            # administrator and named in the parameter still gets one popup.
            recipients |= Users.search([("login", "in", logins)])
        return recipients

    def _bus_notification_payload(self):
        """The JSON payload the JS listener renders in the popup."""
        self.ensure_one()
        return {
            "id": self.id,
            "name": self.name,
            "title": self.title or "",
            "category": self.category_id.name or "",
            "author": self.suggested_by_id.name or "",
        }

    def _notify_new_suggestion(self):
        """Push the popup to each recipient over the bus.

        Sent per user rather than to the ``base.group_system`` group channel:
        the group channel would reach every administrator but could not carry
        the extra logins, and mixing the two would double-notify anyone who is
        both. One send per user keeps "exactly one popup per recipient" true
        by construction.
        """
        recipients = self._notification_recipient_users()
        if not recipients:
            return
        for rec in self:
            # res.users inherits bus.listener.mixin and resolves to the user's
            # own partner channel, which every logged-in session subscribes to.
            recipients._bus_send(
                BUS_NOTIFICATION_TYPE, rec._bus_notification_payload()
            )

    def _log_creation_note(self):
        """Record the submission in the chatter, notifying nobody.

        Preserves the audit trail the old email notification left behind. It
        cannot produce an email: an internal note only reaches followers, the
        only follower at this point is the submitter, and Odoo never notifies
        the author of their own message.
        """
        for rec in self:
            rec.message_post(
                body=Markup(
                    "<p>Suggestion submitted by <b>%s</b> under <b>%s</b>.</p>"
                ) % (
                    rec.suggested_by_id.name or "-",
                    rec.category_id.name or "-",
                ),
                subtype_xmlid="mail.mt_note",
            )
