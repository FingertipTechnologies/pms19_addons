# -*- coding: utf-8 -*-
################################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2025-TODAY Cybrosys Technologies(<https://www.cybrosys.com>).
#    Author: Jumana Jabin MP (odoo@cybrosys.com)
#
#    You can modify it under the terms of the GNU AFFERO
#    GENERAL PUBLIC LICENSE (AGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU AFFERO GENERAL PUBLIC LICENSE (AGPL v3) for more details.
#
#    You should have received a copy of the GNU AFFERO GENERAL PUBLIC LICENSE
#    (AGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
################################################################################
from collections import defaultdict
from odoo import fields, models,api
from odoo.exceptions import ValidationError,AccessError



class MailActivity(models.Model):
    """Inherited mail.activity model mostly to add dashboard functionalities"""
    _inherit = "mail.activity"

    activity_tag_ids = fields.Many2many('activity.tag',
                                        string='Activity Tags',
                                        help='Select activity tags.')
    state = fields.Selection(selection_add=[
        ('done', 'Done'),
    ], string='State', help='State of the activity')
    rnr = fields.Boolean()
    parent_partner_id = fields.Many2one(
        'res.partner',
        string='Company',
        domain=[('is_company', '=', True)],
        index=True
    )

    child_partner_id = fields.Many2one(
        'res.partner',
        string='Contact',
        domain="[('parent_id', '=', parent_partner_id)]",
        index=True
    )
    account_status_id = fields.Many2one('res.partner.account.status', string="Account Status")
    # ---------------------------------------------------------
    # Real-time searchable activity dates (NO related fields)
    # ---------------------------------------------------------
    parent_first_activity_datetime = fields.Datetime(index=True,related='parent_partner_id.first_activity_datetime', string='Parent First Activity Datetime')
    parent_last_activity_datetime = fields.Datetime(index=True,related='parent_partner_id.last_activity_datetime', string='Parent Last Activity Datetime')

    child_first_activity_datetime = fields.Datetime(index=True,related='child_partner_id.first_activity_datetime',string='Child First Activity Datetime')
    child_last_activity_datetime = fields.Datetime(index=True,related='child_partner_id.last_activity_datetime',string='Child Last Activity Datetime')

    # ---------------------------------------------------------
    # Defaults when activity created from partner
    # ---------------------------------------------------------
    # @api.model
    # def default_get(self, fields_list):
    #     res = super().default_get(fields_list)
    #
    #     if self.env.context.get('default_res_model') == 'res.partner':
    #         partner = self.env['res.partner'].browse(
    #             self.env.context.get('default_res_id')
    #         )
    #         if partner:
    #             if partner.is_company:
    #                 res.update({
    #                     'parent_partner_id': partner.id,
    #                     'res_model': 'res.partner',
    #                     'res_id': partner.id,
    #                 })
    #             elif partner.parent_id:
    #                 res.update({
    #                     'parent_partner_id': partner.parent_id.id,
    #                     'child_partner_id': partner.id,
    #                     'res_model': 'res.partner',
    #                     'res_id': partner.parent_id.id,
    #                 })
    #     return res

    # ---------------------------------------------------------
    # Always keep activity linked to parent
    # ---------------------------------------------------------
    @api.onchange('parent_partner_id')
    def _onchange_parent_partner_id(self):
        if self.parent_partner_id:
            self.res_model = 'res.partner'
            self.res_id = self.parent_partner_id.id
            self.child_partner_id = False

    # ---------------------------------------------------------
    # Validation
    # ---------------------------------------------------------
    @api.constrains('parent_partner_id', 'child_partner_id')
    def _check_parent_child(self):
        for rec in self:
            if rec.child_partner_id and \
                    rec.child_partner_id.parent_id != rec.parent_partner_id:
                raise ValidationError(
                    "Selected contact does not belong to the selected company."
                )

    def _activity_partner(self):
        """The contact/company this activity is about, or an empty recordset
        for an activity on any other model (a task, a helpdesk ticket, ...)."""
        self.ensure_one()
        partner = self.child_partner_id or self.parent_partner_id
        if not partner and self.res_model == 'res.partner' and self.res_id:
            partner = self.env['res.partner'].browse(self.res_id).exists()
        return partner

    @api.constrains('parent_partner_id', 'child_partner_id', 'res_model', 'res_id')
    def _check_account_details(self):
        """An activity logged against a contact/account requires the mandatory
        account details to be filled in first. Activities on other models are
        untouched."""
        for rec in self:
            partner = rec._activity_partner()
            if partner:
                partner._check_account_details_complete("an Activity")

    def _recompute_partner_activity_dates(self):
        partners = (
                self.mapped('parent_partner_id') |
                self.mapped('child_partner_id')
        )
        partners._compute_activity_dates()

    # ---------------------------------------------------------
    # Core logic: update first / last activity dates
    # ---------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        activities = super().create(vals_list)

        for activity in activities:
            if activity.res_model != 'res.partner':
                continue

            dt = activity.create_date or fields.Datetime.now()
            vals = {}

            # ---------- Parent ----------
            if activity.parent_partner_id:
                first_parent = self.search(
                    [('parent_partner_id', '=', activity.parent_partner_id.id)],
                    order='create_date asc',
                    limit=1
                )
                vals.update({
                    'parent_first_activity_datetime':
                        first_parent.create_date if first_parent else dt,
                    'parent_last_activity_datetime': dt,
                })

            # ---------- Child ----------
            if activity.child_partner_id:
                first_child = self.search(
                    [('child_partner_id', '=', activity.child_partner_id.id)],
                    order='create_date asc',
                    limit=1
                )
                vals.update({
                    'child_first_activity_datetime':
                        first_child.create_date if first_child else dt,
                    'child_last_activity_datetime': dt,
                })

            if vals:
                activity.write(vals)
        activities._recompute_partner_activity_dates()
        return activities

    def write(self, vals):
        res = super().write(vals)

        # Only care if partner mapping changed
        if not {'parent_partner_id', 'child_partner_id'} & set(vals):
            return res

        for activity in self:
            if activity.res_model != 'res.partner':
                continue

            # Use creation time (NOT now)
            dt = activity.create_date or fields.Datetime.now()

            # -------------------------
            # Parent partner update
            # -------------------------
            parent = activity.parent_partner_id
            if parent:
                if not parent.first_activity_datetime:
                    parent.first_activity_datetime = dt
                parent.last_activity_datetime = dt

            # -------------------------
            # Child partner update
            # -------------------------
            child = activity.child_partner_id
            if child:
                if not child.first_activity_datetime:
                    child.first_activity_datetime = dt
                child.last_activity_datetime = dt
        self._recompute_partner_activity_dates()
        return res

    def _action_done(self, feedback=False, attachment_ids=None):
        """Override _action_done to remove the unlink code"""
        # marking as 'done'
        messages = self.env['mail.message']
        next_activities_values = []
        # Search for all attachments linked to the activities we are about to
        # unlink. This way, we
        # can link them to the message posted and prevent their deletion.
        attachments = self.env['ir.attachment'].search_read([
            ('res_model', '=', self._name),
            ('res_id', 'in', self.ids),
        ], ['id', 'res_id'])
        activity_attachments = defaultdict(list)
        for attachment in attachments:
            activity_id = attachment['res_id']
            activity_attachments[activity_id].append(attachment['id'])
        for model, activity_data in self._classify_by_model().items():
            records = self.env[model].browse(activity_data['record_ids'])
            for record, activity in zip(records, activity_data['activities']):
                # extract value to generate next activities
                if activity.chaining_type == 'trigger':
                    vals = (activity.with_context(
                        activity_previous_deadline=activity.date_deadline).
                            _prepare_next_activity_values())
                    next_activities_values.append(vals)
                # post message on activity, before deleting it
                activity_message = record.message_post_with_source(
                    'mail.message_activity_done',
                    attachment_ids=attachment_ids,
                    render_values={
                        'activity': activity,
                        'feedback': feedback,
                        'display_assignee': activity.user_id != self.env.user
                    },
                    mail_activity_type_id=activity.activity_type_id.id,
                    subtype_xmlid='mail.mt_activities',
                )
                if activity.activity_type_id.keep_done:
                    attachment_ids = ((attachment_ids or [])
                                      + activity_attachments.get(activity.id,
                                                                 []))
                    if attachment_ids:
                        activity.attachment_ids = attachment_ids
                # Moving the attachments in the message
                # TODO: Fix void res_id on attachment when you create an
                #  activity with an image
                # directly, see route /web_editor/attachment/add
                if activity_attachments[activity.id]:
                    message_attachments = self.env['ir.attachment'].browse(
                        activity_attachments[activity.id])
                    if message_attachments:
                        message_attachments.write({
                            'res_id': activity_message.id,
                            'res_model': activity_message._name,
                        })
                        activity_message.attachment_ids = message_attachments
                messages += activity_message
        next_activities = self.env['mail.activity']
        if next_activities_values:
            next_activities = self.env['mail.activity'].create(
                next_activities_values)
        for rec in self:
            if rec.state != 'done':
                rec.state = 'done'
                rec.active = False
        return messages, next_activities

    def get_activity(self, activity_id):
        """Method for returning model and id of activity"""
        activity = self.env['mail.activity'].browse(activity_id)
        return {
            'model': activity.res_model,
            'res_id': activity.res_id
        }


    def action_open_document_new(self):
        """Opens the related res.partner record if accessible."""
        self.ensure_one()
        partner_model = self.env['ir.model']._get('res.partner')

        if self.res_model_id.id != partner_model.id:
            return {}

        try:
            partner = self.env['res.partner'].browse(self.res_id)
            partner.check_access_rights('read')
            partner.check_access_rule('read')

            return {
                'type': 'ir.actions.act_window',
                'res_model': 'res.partner',
                'res_id': self.res_id,
                'view_mode': 'form',
                'target': 'current',
                'context': self.env.context,
            }
        except AccessError:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'mail.activity',
                'res_id': self.id,
                'view_mode': 'form',
                'target': 'current',
                'views': [(self.env.ref('mail.mail_activity_view_form_without_record_access').id, 'form')],
            }

class MailActivitySchedule(models.TransientModel):
    _inherit = 'mail.activity.schedule'

    parent_partner_id = fields.Many2one(
        'res.partner',
        string='Company',
        domain=[('is_company', '=', True)]
    )

    child_partner_id = fields.Many2one(
        'res.partner',
        string='Contact',
        domain="[('parent_id', '=', parent_partner_id)]"
    )
    rnr = fields.Boolean()
    account_status_id = fields.Many2one('res.partner.account.status', string="Account Status",related='parent_partner_id.account_status_id')
    # ---------------------------------------------------------
    # Auto-default from active partner
    # ---------------------------------------------------------
    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)

        if self.env.context.get('active_model') == 'res.partner':
            partner = self.env['res.partner'].browse(
                self.env.context.get('active_id')
            )
            if partner:
                if partner.is_company:
                    res['parent_partner_id'] = partner.id
                elif partner.parent_id:
                    res['parent_partner_id'] = partner.parent_id.id
                    res['child_partner_id'] = partner.id
        return res

    # ---------------------------------------------------------
    # Inject parent/child into created activities
    # ---------------------------------------------------------
    def _action_schedule_activities(self):
        # Check the mandatory account details up-front so the user gets the
        # message before anything is created, rather than from the constraint
        # that fires once the partner is written onto the activity.
        partner = self.child_partner_id or self.parent_partner_id
        if partner:
            partner._check_account_details_complete("an Activity")
        activities = super()._action_schedule_activities()

        for activity in activities:
            activity.write({
                'parent_partner_id': self.parent_partner_id.id,
                'child_partner_id': self.child_partner_id.id,
                'rnr':self.rnr,
                'account_status_id': self.account_status_id.id,
            })

        return activities