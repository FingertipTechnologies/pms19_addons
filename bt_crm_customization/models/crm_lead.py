from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError

from odoo.addons.bt_contact_customization.models.res_partner import (
    EMPLOYEE_COUNT_FIELD,
)

from .campaign import SOURCE_SELECTION

# Stage names (case-insensitive) used to drive the mandatory-field rules.
COLD_STAGE = 'cold'
# Business Challenge / Expected Revenue / Expected Closing / Technology become
# mandatory from the Qualified stage onward.
#
# 'lost' is deliberately NOT in this set. A lost opportunity is now moved into
# the Lost stage automatically when it is archived (see
# ft_sales_dashboard/models/crm_lead.py), so that a list, an export or a pivot
# never shows a dead deal sitting in Discussion or Demo. Demanding Business
# Challenge, Technology and an Expected Closing date before a deal may be
# recorded as lost would block that move outright — 241 of the archived
# opportunities in the live database do not carry all four — and it asks for
# forward-looking qualification data about a deal that has already ended.
QUALIFIED_PLUS_STAGES = {
    'qualified', 'estimation', 'proposition', 'negotiation', 'won',
}
WON_STAGE = 'won'
LOST_STAGE = 'lost'
NEXT_ACTION_MIN_LEN = 20

# Context key set by the automatic stage syncs in ft_sales_dashboard, which move
# an opportunity into the Won or Lost stage to match an outcome it already has
# (100% probability, or archived). The mandatory-field rules below step aside for
# it: they cannot conjure the missing data, and refusing the move would only keep
# the stage wrong in every list, export and pivot — the precise problem the sync
# was written to solve. A human moving a deal to Won still faces all of them.
# Spelled out rather than imported, so this module keeps depending on nothing but
# crm; ft_sales_dashboard defines the same value as STAGE_SYNC_CONTEXT.
STAGE_SYNC_CONTEXT = 'ft_stage_sync'


class InheritCrmLead(models.Model):
    _inherit = 'crm.lead'

    account_id = fields.Many2one('res.partner', string='Account')
    features_id = fields.Many2one('cus.features', string='Features')

    # Odoo 19 dropped crm.lead.mobile from core (upstream merged it into phone),
    # but the migration left the `mobile` column and every value in it untouched
    # - only the field registration went away. Re-declaring it here with the
    # same name and a matching type makes Odoo adopt the existing column, so the
    # stored numbers come back with no data migration at all. Keep the name
    # exactly `mobile`: any other name creates a new empty column and leaves the
    # real one orphaned. Most of these records carry a mobile and no phone, so
    # without this the lead looks like it has no number at all.
    mobile = fields.Char(string='Mobile')

    def _phone_get_number_fields(self):
        """Search and sanitize over Phone FIRST, then Mobile.

        The base implementation returns ``['mobile', 'phone']`` - mobile first -
        so simply re-declaring `mobile` above would make `phone_sanitized`
        recompute from the mobile number on the next write of every record that
        has both. `phone_sanitized` is the key SMS blacklist matching runs on,
        and the migration already recomputed it from `phone`, so letting it flip
        would silently re-point the blacklist for the records where the two
        numbers differ. Putting `phone` first keeps those untouched, while
        records with a mobile and no phone - the bulk of what this field brings
        back - still get a sanitized number instead of none.

        Returning both fields (rather than dropping mobile) is also what lets the
        stock "Phone Number" search box match on mobile again, and what makes
        the supporting index in ``init()`` cover the mobile column.
        """
        return [
            fname for fname in ('phone', 'mobile') if fname in self._fields
        ]

    # ------------------------------------------------------------------
    # Mandatory account details, fetched read-only from the Contact
    # ------------------------------------------------------------------
    # Shown on the form so the salesperson can SEE which of the four details is
    # empty, and on which account, instead of only meeting a blocking error.
    # `commercial_partner_id` is the company at the top of the contact's
    # hierarchy, i.e. the account: a child contact resolves to its parent
    # company, a company (or a standalone individual) resolves to itself.
    # Legal Name is not among them: it IS the account's company name, so it is
    # still validated but showing it here would only repeat the Contact.
    account_currency_id = fields.Many2one(
        'res.currency', string="Account Currency",
        related='partner_id.commercial_partner_id.annual_revenue_currency_id',
        readonly=True)
    account_annual_revenue = fields.Monetary(
        string="Annual Revenue", currency_field='account_currency_id',
        related='partner_id.commercial_partner_id.annual_revenue_amount',
        readonly=True)
    account_website = fields.Char(
        string="Account Website",
        related='partner_id.commercial_partner_id.website', readonly=True)
    # Employee Count comes from the manual field 'x_Employee' on the account.
    # Computed rather than related: a manual field is created in the database,
    # so traversing it in a related path is not safe at registry-setup time.
    account_employee_count = fields.Integer(
        string="Employee Count", compute='_compute_account_employee_count')

    @api.depends('partner_id')
    def _compute_account_employee_count(self):
        for lead in self:
            account = lead.partner_id.commercial_partner_id
            lead.account_employee_count = (
                account._account_field_value(EMPLOYEE_COUNT_FIELD)
                if account else 0
            )

    # The channel the lead/opportunity came from. Kept on the original
    # `lead_source` column (it was never exposed in a view and held no data)
    # rather than adding a second source field next to it.
    lead_source = fields.Selection(
        SOURCE_SELECTION, string='Source', tracking=True,
    )
    # Campaign the lead/opportunity came from. Distinct from the stock
    # `campaign_id` (utm.campaign) which stays where Odoo puts it, in the
    # Marketing group of the Extra Info tab.
    cus_campaign_id = fields.Many2one(
        'cus.campaign', string='Campaign', tracking=True,
    )

    owner_id = fields.Many2one('res.users', string='Owner')
    # Business Development Representative. Defaults to whoever creates the
    # opportunity (env.user at creation time == the creator), and stays editable
    # so it can be reassigned later independently of the audit "Created by".
    bdr_id = fields.Many2one(
        'res.users', string='BDR',
        default=lambda self: self.env.user,
        tracking=True,
    )
    technology_id = fields.Many2one('cus.technology', string='Technology')
    profit = fields.Monetary(string='Profit', currency_field='company_currency')
    amount = fields.Monetary(string='Amount', currency_field='company_currency')
    rating = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ], string='Rating')
    revenue = fields.Monetary(string='Closed Amount', currency_field='company_currency')
    source_amount = fields.Monetary(string='Source Amount', currency_field='company_currency')
    cus_type = fields.Selection([
        ('New', 'New'),
        ('Exisitng', 'Exisitng'),
    ], string='Type')

    use_case = fields.Text(string='Use Case')

    # Helper currency field
    company_currency = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id.id
    )


    business_challenge = fields.Text(string="Business Challenge")

    decision_maker = fields.Text(string="Decision Maker")

    number_of_users = fields.Integer(string="Number of Users")

    next_action = fields.Text(string="Next Action")

    description_text = fields.Text(string="Description")

    linkedin_url = fields.Char(string="LinkedIn URL")

    # ------------------------------------------------------------------
    # Lead qualification fields (Lead page)
    # ------------------------------------------------------------------
    # The date the lead came in. Deliberately a separate stored Date rather
    # than a related field on the technical `create_date`: leads are also
    # entered days after the first contact and imported from spreadsheets, so
    # the business date has to stay editable. It defaults to the day the record
    # is created, which is the value `create_date` would have given anyway.
    lead_created_date = fields.Date(
        string="Created Date", default=fields.Date.context_today,
        tracking=True,
        help="Date the lead was created / first received.",
    )
    # The CRM (if any) the prospect runs today. Kept to exactly the four values
    # the business asked for - no free text, so it stays groupable.
    current_system = fields.Selection([
        ('zoho', 'Zoho'),
        ('none_spreadsheet', 'None - Spreadsheet'),
        ('other', 'Other'),
        ('hubspot', 'HubSpot'),
    ], string="Current System", tracking=True,
        help="System the prospect is using today.")
    # Text, not the Integer employee count read from the account: on a lead the
    # size is whatever the caller was told ("about 40", "50-100 across 3
    # branches"), and the account does not exist yet.
    company_size = fields.Char(
        string="Company Size",
        help="Company size as reported by the prospect (e.g. 50-100 employees).",
    )
    employee_count = fields.Integer(
        string="Employee Count",
        help="Number of employees to copy to the account when the lead is converted.",
    )
    annual_revenue_amount = fields.Monetary(
        string="Annual Revenue",
        currency_field='company_currency',
        help="Annual revenue to copy to the account when the lead is converted.",
    )
    acquisition_timeline = fields.Selection([
        ('just_exploring', 'Just Exploring'),
        ('1_3_months', '1-3 Months'),
        ('this_month', 'This Month'),
    ], string="Timeline", tracking=True,
        help="When the prospect is ready to acquire.")
    # Outcome of the call / first touch. Distinct from `stage_id` (the pipeline
    # position) and from the stock `won_status`: a lead can sit in the first
    # stage with a status of RNP for several attempts.
    lead_status = fields.Selection([
        ('call_taken', 'Call Taken'),
        ('rnp', 'RNP'),
        ('busy', 'Busy'),
        ('not_interested', 'Not Interested'),
        ('by_mistake', 'By Mistake'),
        ('junk', 'Junk'),
    ], string="Status", tracking=True,
        help="Outcome of the last contact attempt. RNP = Ring No Pick.")
    # Free text: on a lead this is what the prospect said ("Chennai",
    # "Dubai - HQ in London"), captured before the address fields are filled.
    lead_location = fields.Char(
        string="Location",
        help="Lead / company location.",
    )

    # Snapshot of `next_action` as it was at the last stage change. Used to make
    # sure the user actually updates Next Action between two stage changes.
    last_stage_next_action = fields.Text(
        string="Next Action (last stage change)", copy=False,
    )

    # Stage helper flags, used by the form view to drive the mandatory fields.
    is_cold_stage = fields.Boolean(
        string="Is Cold Stage", compute='_compute_stage_flags',
    )
    require_qualified_fields = fields.Boolean(
        string="Require Qualified Fields", compute='_compute_stage_flags',
        help="True from the Qualified stage onward.",
    )
    is_won_stage = fields.Boolean(
        string="Is Won Stage", compute='_compute_stage_flags',
    )
    is_lost_stage = fields.Boolean(
        string="Is Lost Stage", compute='_compute_stage_flags',
    )

    @api.depends('stage_id', 'stage_id.name')
    def _compute_stage_flags(self):
        for lead in self:
            name = (lead.stage_id.name or '').strip().lower()
            lead.is_cold_stage = name == COLD_STAGE
            lead.require_qualified_fields = name in QUALIFIED_PLUS_STAGES
            lead.is_won_stage = name == WON_STAGE
            lead.is_lost_stage = name == LOST_STAGE

    @api.onchange('partner_id')
    def _onchange_partner_id_account_details(self):
        """Tell the user straight away which account details are missing, so
        they don't only find out when the save is rejected."""
        if self.type != 'opportunity' or not self.partner_id:
            return
        missing = self.partner_id._missing_account_fields()
        if missing:
            return {'warning': {
                'title': "Incomplete Account Information",
                'message': (
                    "The account '%s' is missing: %s.\n\n"
                    "Please complete these details on the account before "
                    "saving this opportunity." % (
                        self.partner_id.commercial_partner_id.display_name,
                        ', '.join(missing),
                    )
                ),
            }}

    @api.constrains('partner_id', 'type')
    def _check_opportunity_contact(self):
        """An opportunity always needs a Contact, and that contact's account
        must carry the mandatory details (Annual Revenue, Employee Count,
        Website, Legal Name) before the opportunity may be created.

        Leads are deliberately exempt: a lead is captured before the account is
        known, and it is the conversion to an opportunity - which writes
        `type` and `partner_id` - that runs this check.
        """
        for lead in self:
            if lead.type != 'opportunity':
                continue
            if not (lead.contact_name or '').strip():
                raise ValidationError(
                    "Contact Name is required to create an opportunity. "
                    "Please enter the contact name on the lead before converting it."
                )
            if not lead.partner_id:
                raise ValidationError(
                    "Contact is required to create an opportunity. "
                    "Please select a contact before saving."
                )
            lead.partner_id._check_account_details_complete("an Opportunity")

    @api.constrains('next_action', 'stage_id', 'type')
    def _check_next_action(self):
        """Next Action is mandatory (min 20 chars) except in Cold and Lost.

        Lost is exempt for the same reason it left QUALIFIED_PLUS_STAGES: there
        is no next action on a deal that has ended, and requiring one would stop
        the automatic move into the Lost stage on archive. The Won sync in
        ft_sales_dashboard is exempt for the same reason — a deal that has been
        won has no next action either, and the record is already won whether or
        not its stage is allowed to say so.

        The stage name is read straight off ``stage_id`` rather than through the
        ``is_cold_stage`` / ``is_lost_stage`` computes, because those two are
        unreliable in the one place it matters most - converting a lead.

        ``crm.lead.stage_id`` is a computed *stored* field that depends on
        ``type``, so writing ``type = 'opportunity'`` queues it for recompute.
        ``_check_closed_amount`` then reads ``is_won_stage``, which enters
        ``_compute_stage_flags``, which reads ``stage_id``, which fires that
        pending recompute, which re-validates ``stage_id`` and re-enters this
        constraint - all while ``_compute_stage_flags`` is still on the stack.
        The flags are therefore mid-compute and read falsy, the Cold exemption
        is skipped, and a Cold lead cannot be converted at all. Every lead in
        the database sits in Cold, so this blocked every conversion.

        Reading ``stage_id.name`` here has no such problem: by the time this
        runs, ``stage_id`` itself has been computed.
        """
        if self.env.context.get(STAGE_SYNC_CONTEXT):
            return
        for lead in self:
            stage_name = (lead.stage_id.name or '').strip().lower()
            if lead.type != 'opportunity' or stage_name in (COLD_STAGE, LOST_STAGE):
                continue
            text = (lead.next_action or '').strip()
            if not text:
                raise ValidationError(
                    "Next Action is required for opportunities in every stage except Cold."
                )
            if len(text) < NEXT_ACTION_MIN_LEN:
                raise ValidationError(
                    "Next Action must be at least %d characters long." % NEXT_ACTION_MIN_LEN
                )

    @api.constrains('expected_revenue', 'date_deadline', 'business_challenge',
                    'technology_id', 'stage_id', 'type')
    def _check_qualified_fields(self):
        """Business Challenge, Expected Revenue, Expected Closing and Technology
        are mandatory from the Qualified stage onward (Expected Revenue must be
        non-zero, as 0 counts as 'filled' for a monetary field).

        Exempt for the automatic Won-stage sync, which lands records in 'won' —
        a member of QUALIFIED_PLUS_STAGES — without anyone having filled these
        in on the way past.
        """
        if self.env.context.get(STAGE_SYNC_CONTEXT):
            return
        for lead in self:
            if lead.type != 'opportunity' or not lead.require_qualified_fields:
                continue
            missing = []
            if not lead.expected_revenue:
                missing.append('Expected Revenue')
            if not lead.date_deadline:
                missing.append('Expected Closing')
            if not lead.business_challenge:
                missing.append('Business Challenge')
            if not lead.technology_id:
                missing.append('Technology')
            if missing:
                raise ValidationError(
                    "The following fields are required from the Qualified stage "
                    "onward: %s." % ', '.join(missing)
                )

    @api.constrains('revenue', 'stage_id', 'type')
    def _check_closed_amount(self):
        """Closed Amount is mandatory (non-zero) on the Won stage.

        Skipped for the automatic Won-stage sync. That move does not win the
        deal — the deal was already won, at 100% probability, when this rule
        never got a chance to run — it only makes the stage say so. Blocking it
        would not produce a Closed Amount; it would leave the record won with
        its stage still reading Demo, which is the bug the sync exists to fix.
        The rule still applies in full to anyone moving a deal to Won by hand,
        and to the next manual save of a synced record.
        """
        if self.env.context.get(STAGE_SYNC_CONTEXT):
            return
        for lead in self:
            if lead.type == 'opportunity' and lead.is_won_stage and not lead.revenue:
                raise ValidationError(
                    "Closed Amount is required (and must be greater than 0) on the Won stage."
                )

    def _prepare_customer_values(self, partner_name, is_company=False, parent_id=False):
        """Carry lead qualification data into a customer created on conversion.

        Core CRM calls this method once for the company and, when the lead also
        has a contact name, once more for the child contact. The mandatory
        values belong to the account, so put them on the company (or on the
        standalone customer when no company is created), not on a child.
        """
        values = super()._prepare_customer_values(
            partner_name, is_company=is_company, parent_id=parent_id,
        )
        if not parent_id:
            values.update({
                EMPLOYEE_COUNT_FIELD: self.employee_count,
                'annual_revenue_amount': self.annual_revenue_amount,
                'annual_revenue_currency_id': self.company_currency.id,
            })
        return values

    def _create_customer(self, with_parent=None):
        """Reject conversion before core CRM invents fallback customer names.

        Core CRM can create a standalone customer from the lead title when the
        company/contact names are missing, then synchronize generated values
        back onto the lead. A later constraint therefore cannot reliably tell
        which source fields were originally empty.
        """
        self.ensure_one()
        missing = []
        if not (self.partner_name or '').strip():
            missing.append("Company Name")
        if not (self.contact_name or '').strip():
            missing.append("Contact Name")
        if missing:
            raise ValidationError(
                "%s required to create an opportunity. Please complete the "
                "lead before converting it." % (
                    "%s %s" % (
                        " and ".join(missing),
                        "is" if len(missing) == 1 else "are",
                    )
                )
            )
        return super()._create_customer(with_parent=with_parent)

    def write(self, vals):
        """Force the user to update 'Next Action' before any stage change.

        The check compares the effective Next Action (the value being written,
        or the current one) against the snapshot stored at the last stage
        change. This works both for a form save (Next Action + stage in one
        write) and for a Kanban drag (only stage_id is written) as long as
        Next Action was updated since the previous stage change.
        """
        stage_changing = self.browse()
        # Moving INTO Lost is exempt: that move is made automatically when an
        # opportunity is archived, and there is no next action to record on a
        # deal that has ended. Without this the automatic move would raise and
        # the archive would fail.
        target_is_lost = bool(vals.get('stage_id')) and (
            self.env['crm.stage'].browse(vals['stage_id']).name or ''
        ).strip().lower() == LOST_STAGE
        # Same exemption for the automatic Won-stage sync, which reconciles the
        # stage with a win the record already carries rather than making one.
        automatic = target_is_lost or self.env.context.get(STAGE_SYNC_CONTEXT)
        if 'stage_id' in vals and not automatic:
            new_stage = vals.get('stage_id')
            for lead in self:
                if lead.type != 'opportunity' or lead.stage_id.id == new_stage:
                    continue
                effective_next = (
                    vals['next_action'] if 'next_action' in vals else lead.next_action
                ) or ''
                if effective_next.strip() == (lead.last_stage_next_action or '').strip():
                    raise UserError(
                        "Please update the 'Next Action' before changing the stage"
                        " of '%s'." % (lead.name or '')
                    )
                stage_changing |= lead
        res = super().write(vals)
        # Snapshot the new Next Action for the records whose stage just changed.
        for lead in stage_changing:
            super(InheritCrmLead, lead).write(
                {'last_stage_next_action': lead.next_action or ''}
            )
        # No blanket re-check of Closed Amount here. It used to run on every
        # save of a Won record, to catch one that reached the stage without an
        # amount — which, while the @api.constrains above was the only way in,
        # could not happen: a record could only arrive on Won by passing it.
        #
        # The automatic Won-stage sync in ft_sales_dashboard is now a second way
        # in, and it is deliberately exempt (a deal won at 100% probability is
        # already won; refusing to label its stage would not produce an amount).
        # This line therefore had exactly one population left to fire on — the
        # records the sync had just placed — and it fired on every subsequent
        # edit of them, from the sync's own follow-up write onward, making them
        # unsaveable. Clearing the amount by hand is still caught, because that
        # write names ``revenue`` and so triggers the constraint directly.
        return res
