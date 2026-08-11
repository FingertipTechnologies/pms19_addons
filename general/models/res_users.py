from odoo import api, fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    # Why this field exists
    # ---------------------
    # Two fields on res.users were already labelled "Job Position":
    #
    #   * ``function``  - a Char inherited from res.partner (the contact's
    #                     free-text job title)
    #   * ``job_title`` - a Char related to employee_id.job_title
    #
    # Both are plain text, so "Add Custom Filter -> Job Position" on the Users
    # list offered a free-text box with no dropdown: there is nothing for the
    # filter editor to pick from. Odoo's hr module relates job_title to the
    # employee but deliberately does not expose the employee's job_id.
    #
    # hr.employee.job_id IS a Many2one to hr.job (the Job Positions configured
    # under Employees > Recruitment Management), so relating to it gives the
    # filter a real record picker listing exactly those positions.
    job_id = fields.Many2one(
        related='employee_id.job_id',
        readonly=False,
        related_sudo=False,
        string='Job Position',
        help="Job Position from the linked employee record. Filterable as a "
             "dropdown, unlike the free-text Job Position on the contact.",
    )

    # ``function`` is the contact's free-text job title, delegated to res.users
    # from res.partner. It is plain text, so it can only ever offer a typing box
    # in "Add Custom Filter" — next to the real Job Position above it was pure
    # confusion, so it is hidden from the field selector here.
    #
    # The selector keeps only fields whose description is searchable, and
    # ``_description_searchable`` is ``bool(store or search)``. Redeclaring the
    # field as a non-stored compute with no search method therefore drops it
    # from the list. The compute/inverse pair keeps reading and writing working
    # exactly as before against the underlying partner, so no data or existing
    # behaviour is lost — only the filter entry disappears.
    function = fields.Char(
        string='Job Position (Contact)',
        compute='_compute_function',
        inverse='_inverse_function',
        store=False,
        readonly=False,
    )

    @api.depends('partner_id.function')
    def _compute_function(self):
        for user in self:
            user.function = user.partner_id.function

    def _inverse_function(self):
        for user in self:
            user.partner_id.function = user.function

    @property
    def SELF_READABLE_FIELDS(self):
        # Without this a non-HR user reading their own record is refused
        # access to the new field, which breaks the Preferences dialog.
        return super().SELF_READABLE_FIELDS + ['job_id']

    @property
    def SELF_WRITEABLE_FIELDS(self):
        # Mirrors job_title, which core hr makes self-writeable.
        return super().SELF_WRITEABLE_FIELDS + ['job_id']
