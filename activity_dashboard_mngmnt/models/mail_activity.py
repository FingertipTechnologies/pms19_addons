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
from odoo import fields, models, api, _
from odoo.exceptions import ValidationError, AccessError, UserError



class MailActivity(models.Model):
    """Inherited mail.activity model mostly to add dashboard functionalities"""
    _inherit = "mail.activity"

    activity_tag_ids = fields.Many2many('activity.tag',
                                        string='Activity Tags',
                                        help='Select activity tags.')
    # `search=` is the point of this override, not `selection_add`: core already
    # ships a 'done' value, so the addition is a no-op kept only for
    # compatibility with databases that stored it.
    #
    # core's mail.activity.state is compute=..., with no store and no search, so
    # ANY domain on it raises "Cannot convert mail.activity.state to SQL because
    # it is not stored". The Activity Dashboard filters on exactly that
    # (state = planned / today / overdue / done), which is why opening it in the
    # CRM module returned a 500. Two of the four dashboard queries already OR'd
    # in a date_deadline condition as a workaround, but the `state` term was
    # still there and it is the term that raises.
    state = fields.Selection(
        selection_add=[('done', 'Done')],
        string='State',
        help='State of the activity',
        search='_search_state',
    )

    def _search_state(self, operator, value):
        """Translate a domain on `state` into one on date_deadline / active.

        Mirrors core's _compute_state exactly:

            done      -> the activity is archived
            overdue   -> deadline is before today
            today     -> deadline is today
            planned   -> deadline is after today

        `date_deadline` is `required`, so every activity resolves to exactly one
        of the four and negation can be expressed as the complement of the set —
        no activity falls outside it.

        One honest limitation: _compute_state resolves "today" in the ASSIGNED
        USER's timezone, and a search can only use the current user's. An
        activity within a day of the boundary can therefore be bucketed here
        differently from the badge shown on the record itself. Making the two
        agree would need date_deadline stored per-user-timezone, which it is
        not; the dashboard's own JavaScript already compares against a plain
        date, so this is no less accurate than what it replaces.
        """
        states = ('overdue', 'today', 'planned', 'done')
        if operator in ('=', '!='):
            wanted = {value}
        elif operator in ('in', 'not in'):
            wanted = set(value or ())
        else:
            raise UserError(_(
                "Unsupported operator '%s' for the activity State filter. "
                "Use =, !=, in or not in.", operator))
        if operator in ('!=', 'not in'):
            wanted = set(states) - wanted
        wanted &= set(states)
        if not wanted:
            # Matches nothing, rather than silently matching everything.
            return [('id', '=', False)]
        if wanted == set(states):
            return []

        today = fields.Date.context_today(self)
        # `('active', '=', False)` is deliberate for done and `!= False` for the
        # rest: Odoo renders a Boolean compared to False as "IS NULL OR = false",
        # so a row whose `active` was never written still reads as archived —
        # which is what record.active would give the compute.
        per_state = {
            'done': [('active', '=', False)],
            'overdue': [('active', '!=', False), ('date_deadline', '<', today)],
            'today': [('active', '!=', False), ('date_deadline', '=', today)],
            'planned': [('active', '!=', False), ('date_deadline', '>', today)],
        }
        # Each per-state domain is TWO conditions, so it needs its own explicit
        # '&' before it can be OR-ed with another. Without that, Odoo's prefix
        # notation reads ['|', A1, A2, B1, B2] as "(A1 OR A2) AND B1 AND B2"
        # rather than "(A1 AND A2) OR (B1 AND B2)" — which silently returned
        # nothing for `state in ('today', 'overdue')` while each state on its
        # own worked, because a single sub-domain gets the implicit AND.
        def _all_of(conditions):
            return ['&'] * (len(conditions) - 1) + conditions

        subdomains = [_all_of(per_state[state]) for state in sorted(wanted)]
        domain = subdomains[0]
        for subdomain in subdomains[1:]:
            domain = ['|'] + domain + subdomain
        return domain
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

    # `_action_done` used to be overridden here, as a copy of the Odoo 17
    # implementation with its `unlink()` taken out, so that a completed
    # activity stayed on the record for the dashboard to report on.
    #
    # Odoo 19 does exactly that itself: core `_action_done` archives the
    # activity (`action_archive()`) instead of deleting it, and `state` is
    # computed as 'done' for any archived activity. The copy had therefore
    # become a stale fork that also crashed - it read
    # `activity_type_id.keep_done`, a field upstream dropped from
    # mail.activity.type, so every 'Mark as Done' raised AttributeError -
    # and it missed everything core gained since: the sudo access for users
    # who may not read the record, the handling of cascade-deleted records,
    # the cleanup of orphaned attachments and the storing of `feedback`.
    # Removed rather than patched: core's own method is now the behaviour
    # this module wanted.

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