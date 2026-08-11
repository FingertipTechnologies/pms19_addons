import re

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

# A normal company website must start with "https://www." and end at the TLD
# with NOTHING after it: no path, no trailing slash, no query string.
# e.g. https://www.acme.com -> OK     https://www.acme.com/about -> rejected
#      www.acme.com / http://acme.com -> rejected (must be https://www.)
WEBSITE_RE = re.compile(r'^https://www\.([a-z0-9-]+\.)+[a-z]{2,}$', re.IGNORECASE)

# Hosts shared by many companies - link-in-bio pages, social profiles and URL
# shorteners. The domain alone is NOT unique to one company: the PATH is what
# identifies the company (e.g. https://linktr.ee/acme vs https://linktr.ee/bar).
# For these hosts we keep the path when matching, checking uniqueness and
# storing, and we do NOT force a "www." prefix (these services don't use it).
SHARED_DOMAIN_HOSTS = frozenset({
    'linktr.ee', 'linktree.com',
    'instagram.com', 'facebook.com', 'm.facebook.com', 'fb.com',
    'twitter.com', 'x.com',
    'linkedin.com',
    'youtube.com', 'youtu.be',
    'bit.ly', 'tinyurl.com', 't.co',
    'wa.me', 'api.whatsapp.com',
    'sites.google.com', 'business.google.com', 'g.page',
    'beacons.ai', 'campsite.bio', 'carrd.co', 'about.me', 'taplink.cc',
})

# For a shared-domain host the URL may carry a path (e.g. https://linktr.ee/acme).
# Host, optionally followed by a path, with no trailing slash / query / fragment.
SHARED_WEBSITE_RE = re.compile(
    r'^https://([a-z0-9-]+\.)+[a-z]{2,}(/[^\s?#]+)?$', re.IGNORECASE)

# Employee Count is the manually-created (Studio) field 'x_Employee' that
# already holds the head count on every account. It lives in the database, not
# in this module, so it is referenced by name and read defensively.
EMPLOYEE_COUNT_FIELD = 'x_Employee'

# Account (company) details that must be filled in before an Opportunity or an
# Activity may be created against that account. (field name, label shown to the
# user), in the order they are listed back in the error message.
# Legal Name is the account's company name (`name`) - there is no separate
# legal-name field.
ACCOUNT_REQUIRED_FIELDS = [
    ('annual_revenue_amount', 'Annual Revenue'),
    (EMPLOYEE_COUNT_FIELD, 'Employee Count'),
    ('website', 'Website'),
    ('name', 'Legal Name'),
]


class InheritResPartner(models.Model):
    _inherit = 'res.partner'

    account_status_id = fields.Many2one('res.partner.account.status', string="Account Status")

    rating = fields.Selection([
        ('hot', 'Hot'),
        ('cold', 'Cold'),
        ('warm', 'Warm'),

    ], string="Rating")


    #activity_count_custom = fields.Integer(string="Activity Count")
    activity_count_custom = fields.Integer(string="Activity Count",compute="_compute_activity_count_custom")

    connected_contacts = fields.Many2many(
        'res.partner',
        'res_partner_connected_rel',
        'partner_id',
        'connected_partner_id',
        string="Connected Contacts"
    )

    number_of_contacts = fields.Integer(
        string="Number of Contacts",
        compute="_compute_number_of_contacts"
    )

    @api.depends('connected_contacts')
    def _compute_number_of_contacts(self):
        for partner in self:
            partner.number_of_contacts = len(partner.connected_contacts)

   


    @api.depends('activity_ids')
    def _compute_activity_count_custom(self):
        Activity = self.env['mail.activity']

        for partner in self:
            domain = [
                    ('res_model', '=', partner._name),
                    ('res_id', 'in', partner.ids),
                    ('active', 'in', [True, False]),
                ]
            partner.activity_count_custom =  Activity.search_count(domain)
    # Legacy Annual Revenue (Integer, ~10 digits). Kept so existing data is not
    # lost, but hidden in the UI; superseded by annual_revenue_amount below.
    annual_revenue = fields.Integer(string="Annual Revenue (legacy)")
    # New Annual Revenue: Monetary, stored as double precision so it holds whole
    # numbers exactly up to ~9.0 quadrillion (16 digits).
    annual_revenue_currency_id = fields.Many2one(
        'res.currency', string="Currency",
        default=lambda self: self.env.company.currency_id)
    annual_revenue_amount = fields.Monetary(
        string="Annual Revenue", currency_field='annual_revenue_currency_id')
    annual_revenue_range = fields.Char(string="Annual Revenue Range")
    company_linkedin = fields.Char(string="Company LinkedIn")

    # ------------------------------------------------------------------
    # Mandatory account details
    # ------------------------------------------------------------------
    def _account_partner(self):
        """The account (company record) this partner belongs to.

        A child contact is validated against its parent company; a company - or
        a standalone individual with no parent - is validated against itself.
        `commercial_partner_id` resolves that in one step, and handles contacts
        nested more than one level deep."""
        self.ensure_one()
        return self.commercial_partner_id or self

    def _account_field_value(self, field_name):
        """Read a mandatory account detail. Looked up defensively because
        Employee Count ('x_Employee') is a manual field defined in the database
        rather than in this module: if it were ever removed, the account simply
        counts as incomplete instead of every save crashing."""
        self.ensure_one()
        return self[field_name] if field_name in self._fields else False

    def _missing_account_fields(self):
        """Labels of the mandatory account details that are still empty on this
        partner's account. Empty list means the account is complete."""
        account = self._account_partner()
        return [
            label for field_name, label in ACCOUNT_REQUIRED_FIELDS
            if not account._account_field_value(field_name)
        ]

    def _check_account_details_complete(self, document):
        """Block the creation of `document` (e.g. "an Opportunity") when the
        account is missing any of the mandatory details, naming every missing
        field so the user knows exactly what to complete."""
        self.ensure_one()
        missing = self._missing_account_fields()
        if missing:
            account = self._account_partner()
            raise ValidationError(_(
                "You cannot create %(document)s for '%(contact)s': the account "
                "'%(account)s' is missing the following mandatory "
                "information - %(missing)s.\n\n"
                "Please complete the account details before proceeding.",
                document=document,
                contact=self.display_name,
                account=account.display_name,
                missing=', '.join(missing),
            ))
    contact_date = fields.Date(string="Contact Date")
    # Dedicated rich-text Description, shown as its own notebook tab.
    description = fields.Html(string="Description")
    duplicate_check = fields.Boolean(string="Duplicate")
    company_eid = fields.Char(string="EID")
    employees = fields.Many2one('res.users',string="Employee")

    first_activity_datetime = fields.Datetime(
        compute='_compute_activity_dates',
        store=True,
        index=True
    )

    last_activity_datetime = fields.Datetime(
        compute='_compute_activity_dates',
        store=True,
        index=True
    )

    # ---------------------------------------------------------
    # Compute partner activity dates FROM mail.activity
    # ---------------------------------------------------------
    @api.depends(
        'activity_ids',  # fallback (chatter activities)
    )
    def _compute_activity_dates(self):
        Activity = self.env['mail.activity']

        for partner in self:
            if partner.is_company:
                domain = [
                    ('parent_partner_id', '=', partner.id),
                    ('active', 'in', [True, False]),
                ]
            else:
                domain = [
                    ('child_partner_id', '=', partner.id),
                    ('active', 'in', [True, False]),
                ]

            activities = Activity.search(domain, order='create_date asc')

            if activities:
                partner.first_activity_datetime = activities[0].create_date
                partner.last_activity_datetime = activities[-1].create_date
            else:
                partner.first_activity_datetime = False
                partner.last_activity_datetime = False

    pain_points = fields.Text(string="Pain Points")
    source_id = fields.Many2one('utm.source', string="Source")
    sub_vertical = fields.Char(string="Sub Vertical")
    working_date = fields.Date(string="Working Date")
    email_1 = fields.Char(string="Email 1")
    email_2 = fields.Char(string="Email 2")
    mobile_1 = fields.Char(string="Mobile 1")
    contact_eid = fields.Char(string="EID")
    contact_linkedin = fields.Char(string="LinkedIn")
    contact_account = fields.Char(string="Account")
    company_domain = fields.Char(string="Company Domain")
    # department = fields.Many2one('res.partner.industry',string="Department")
    department = fields.Char(string="Department")

    # Stored, indexed match key derived from the website. Lets website matching
    # and the uniqueness check use a single indexed query instead of loading and
    # re-parsing every company in Python (which made bulk imports O(N^2)).
    website_key = fields.Char(
        string="Website Key", compute='_compute_website_key',
        store=True, index=True, copy=False)

    @api.depends('website')
    def _compute_website_key(self):
        for partner in self:
            partner.website_key = self._website_key(partner.website)

    # ------------------------------------------------------------------
    # Salesperson sync: company's salesperson flows down to child contacts
    # ------------------------------------------------------------------
    @api.model
    def _normalize_website(self, website):
        """Normalise a website to its bare domain, used for matching and as the
        basis for the standard stored value. Strips scheme, 'www.', any
        path/query/fragment, credentials/port and trailing slash/dots, then
        lowercases. e.g. 'https://www.Google.com/search?q=x' -> 'google.com'.

        Pure string handling (no urlparse) so malformed values - brackets,
        stray colons, etc. - never raise (urlparse can throw 'Invalid IPv6 URL')
        and never break an import."""
        if not website:
            return ''
        value = str(website).strip().lower()
        if not value:
            return ''
        # Strip a leading scheme, tolerating malformed ones written without the
        # colon or with the wrong number of slashes: http://, https://, http//,
        # https//, http:/, https:, etc. Requires http/https followed by at least
        # one ':' or '/' so real domains like 'httpbin.org' are left intact.
        value = re.sub(r'^https?[:/]+', '', value)
        # Drop any remaining leading slashes (e.g. '//example.com').
        value = value.lstrip('/')
        # Cut off anything from the first path / query / fragment separator.
        for sep in ('/', '?', '#'):
            cut = value.find(sep)
            if cut != -1:
                value = value[:cut]
        # Drop 'user:pass@' credentials and any ':port' suffix.
        value = value.split('@')[-1].split(':')[0]
        # Strip a leading 'www.'.
        if value.startswith('www.'):
            value = value[4:]
        return value.strip().strip('.')

    @api.model
    def _is_shared_host(self, host):
        """True when the bare domain is a link-in-bio / social / shortener host
        that is shared across many companies (see SHARED_DOMAIN_HOSTS)."""
        return host in SHARED_DOMAIN_HOSTS

    @api.model
    def _website_path(self, website):
        """Return the URL path (no leading/trailing slash, without query or
        fragment), lowercased, or '' when there is none.
        e.g. 'https://linktr.ee/GkrsProperties/' -> 'gkrsproperties'."""
        if not website:
            return ''
        value = str(website).strip()
        value = re.sub(r'^https?[:/]+', '', value, flags=re.IGNORECASE)
        value = value.lstrip('/')
        slash = value.find('/')
        if slash == -1:
            return ''
        rest = value[slash + 1:]
        for sep in ('?', '#'):
            cut = rest.find(sep)
            if cut != -1:
                rest = rest[:cut]
        return rest.strip().strip('/').lower()

    @api.model
    def _website_key(self, website):
        """The value used to compare / match websites. For a normal company
        domain it's the bare domain; for a shared-domain host the path is
        included so each company's page counts as distinct.
        e.g. acme.com -> 'acme.com'    linktr.ee/acme -> 'linktr.ee/acme'."""
        host = self._normalize_website(website)
        if not host:
            return ''
        if self._is_shared_host(host):
            path = self._website_path(website)
            return '%s/%s' % (host, path) if path else host
        return host

    @api.model
    def _standardize_website(self, website):
        """Return the website in its standard stored format, or '' when there is
        no usable domain. A normal company domain is stored as
        'https://www.<domain>'. A shared-domain host keeps its path and is
        stored as 'https://<host>/<path>' (no forced 'www.', since these
        services don't use it) so different companies on the same host stay
        distinct."""
        host = self._normalize_website(website)
        if not host:
            return ''
        if self._is_shared_host(host):
            path = self._website_path(website)
            return 'https://%s/%s' % (host, path) if path else 'https://%s' % host
        return 'https://www.%s' % host

    @api.model
    def _find_company_by_website(self, website):
        """Return an existing company (is_company=True) whose website matches
        the given one, ignoring scheme/www/trailing slash differences. Matching
        uses the path for shared-domain hosts (so linktr.ee/a != linktr.ee/b)
        and the bare domain for normal company sites."""
        key = self._website_key(website)
        if not key:
            return self.browse()
        # Single indexed lookup on website_key (was: load every company and
        # re-parse its website in Python).
        return self.search([
            ('is_company', '=', True),
            ('website_key', '=', key),
        ], limit=1)

    @api.model
    def _company_name_from_website(self, website):
        """Derive a readable company name from a website, used as a fallback
        when an imported contact has no company-name column. e.g.
        'https://www.acme-corp.com/about' -> 'Acme Corp'."""
        domain = self._normalize_website(website)
        if not domain:
            return ''
        label = domain.split('/')[0].split('.')[0]
        return label.replace('-', ' ').replace('_', ' ').title() or domain

    @api.constrains('website')
    def _check_website_format(self):
        """A normal company website must start with 'https://www.' and be a
        domain only (e.g. https://www.example.com) with nothing after it. A
        shared-domain host (link-in-bio / social / shortener) may include a
        path (e.g. https://linktr.ee/acme) and is not required to use 'www.'."""
        for partner in self:
            if not partner.website:
                continue
            value = partner.website.strip()
            host = self._normalize_website(value)
            if self._is_shared_host(host):
                if not SHARED_WEBSITE_RE.match(value):
                    raise ValidationError(_(
                        "Invalid website '%s'. For a link-in-bio / social page "
                        "use the form https://linktr.ee/yourname (https, no "
                        "spaces).",
                        partner.website,
                    ))
            elif not WEBSITE_RE.match(value):
                raise ValidationError(_(
                    "Invalid website '%s'. It must start with 'https://www.' "
                    "and be a domain only, like https://www.example.com, "
                    "with nothing after it (no '/', path, or extra characters).",
                    partner.website,
                ))

    @api.constrains('website', 'is_company')
    def _check_unique_company_website(self):
        """A company's website must be unique across companies. Matching
        ignores scheme/www/trailing-slash differences. Individuals and child
        contacts are not checked (they may share the company's website)."""
        for partner in self:
            if not partner.is_company:
                continue
            key = partner.website_key
            if not key:
                continue
            # Single indexed lookup on website_key (was: load every other company
            # and re-parse its website in Python for each record being checked).
            other = self.search([
                ('id', '!=', partner.id),
                ('is_company', '=', True),
                ('website_key', '=', key),
            ], limit=1)
            if other:
                raise ValidationError(_(
                    "The website '%s' is already used by company '%s'. "
                    "A company's website must be unique.",
                    partner.website, other.name,
                ))

    @api.model
    def _vals_is_company(self, vals):
        """Decide whether the values describe a company. The web form sends
        ``company_type`` (the Individual/Company toggle), not ``is_company``
        directly, so we must honour both to avoid mis-classifying a company
        as a contact."""
        if 'is_company' in vals:
            return bool(vals['is_company'])
        if vals.get('company_type'):
            return vals['company_type'] == 'company'
        return False

    @api.model_create_multi
    def create(self, vals_list):
        # results keeps the original order; entries are either an already
        # existing company (reused) or are filled in after super().create().
        results = [self.browse()] * len(vals_list)
        to_create = []  # list of (original_index, vals)

        for index, vals in enumerate(vals_list):
            # Standardise the website to 'https://www.<domain>' before any
            # matching or saving, so imports / manual creates all store a
            # consistent value and de-duplication is reliable.
            if vals.get('website'):
                vals['website'] = self._standardize_website(vals['website'])
            is_company = self._vals_is_company(vals)

            # Identify a company by its website (NOT its name): if a company
            # with the same website already exists, reuse it instead of
            # creating a duplicate (e.g. during bulk import).
            if is_company and vals.get('website'):
                existing = self._find_company_by_website(vals['website'])
                if existing:
                    results[index] = existing
                    continue

            # A contact's company is determined by its WEBSITE only. Even if the
            # import row maps a company column (parent_id), it is overridden so
            # placement is based on the website alone. If no company owns that
            # website yet, auto-create it (named from the company-name column,
            # else from the website domain) so the contact is always grouped
            # under the website's company.
            if not is_company and vals.get('website'):
                company = self._find_company_by_website(vals['website'])
                if not company:
                    # A company auto-created while placing a contact is owned by
                    # whoever triggers the create (e.g. the importing user), so
                    # it gets a Salesperson just like accounts made via the
                    # upload wizard's _company_vals.
                    company = self.create({
                        'name': vals.get('company_name') or self._company_name_from_website(vals['website']),
                        'is_company': True,
                        'website': vals['website'],
                        'user_id': self.env.uid,
                    })
                vals['parent_id'] = company.id

            # Default the Salesperson for every new record that doesn't already
            # have one: a child contact first inherits its parent company's
            # salesperson (when the company has one); otherwise — and for any
            # record with no parent — it falls back to the logged-in user. This
            # ensures a contact/account created OR imported is always owned by
            # its creator. self.env.uid stays the real user even under sudo().
            if not vals.get('user_id'):
                parent = self.browse(vals['parent_id']) if vals.get('parent_id') else self.browse()
                vals['user_id'] = parent.user_id.id if parent.user_id else self.env.uid

            to_create.append((index, vals))

        if to_create:
            created = super().create([vals for _index, vals in to_create])
            for (index, _vals), record in zip(to_create, created):
                results[index] = record

        # Return a recordset preserving the original order of vals_list.
        result = self.browse()
        for record in results:
            result += record
        return result

    def write(self, vals):
        # Keep the stored website in the standard 'https://www.<domain>' form
        # whenever it is edited.
        if vals.get('website'):
            vals['website'] = self._standardize_website(vals['website'])
        res = super().write(vals)
        if 'user_id' in vals:
            companies = self.filtered('is_company')
            if companies:
                children = companies.mapped('child_ids').filtered(
                    lambda c: not c.is_company
                )
                # Option B (default): always overwrite child's salesperson with company's.
                # For Option A (preserve manual overrides), add: .filtered(lambda c: not c.user_id)
                if children:
                    children.write({'user_id': vals['user_id']})
        return res

