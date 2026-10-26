from urllib.parse import quote as url_quote

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from odoo.fields import Command

from .hr_employee import (
    BANK_ACCOUNT_TYPES, INDIA_STATE_DOMAIN, VIEWABLE_COPIES, PRESENT_TO_PERMANENT,
)
# Groups that may see and edit the personal details of *every* employee.
DETAILS_ADMIN_GROUPS = ('hr.group_hr_user', 'base.group_system')



# Personal-detail fields shown on hr.employee.public -> source field on hr.employee.
# Custom fields keep their name; standard fields that already exist (job_title)
# or are HR-only on hr.employee (birthday, marital) get a "details_" proxy name.
PUBLIC_TO_EMPLOYEE_FIELDS = {
    'aadhar_no': 'aadhar_no',
    'aadhar_copy': 'aadhar_copy',
    'aadhar_copy_filename': 'aadhar_copy_filename',
    'pan_no': 'pan_no',
    'pan_copy': 'pan_copy',
    'pan_copy_filename': 'pan_copy_filename',
    'bank_copy': 'bank_copy',
    'bank_copy_filename': 'bank_copy_filename',
    'uan_pf_no': 'uan_pf_no',
    'father_name': 'father_name',
    'sex': 'sex',
    'details_birthday': 'birthday',
    'details_marital': 'marital',
    'date_of_joining': 'date_of_joining',
    'details_job_title': 'job_title',
    'present_address': 'present_address',
    'present_state': 'present_state',
    'present_district': 'present_district',
    'present_pin_code': 'present_pin_code',
    'present_mobile': 'present_mobile',
    'present_email': 'present_email',
    'emergency_contact_no': 'emergency_contact_no',
    'permanent_same_as_present': 'permanent_same_as_present',
    'permanent_address': 'permanent_address',
    'permanent_state': 'permanent_state',
    'permanent_district': 'permanent_district',
    'permanent_pin_code': 'permanent_pin_code',
    'permanent_phone': 'permanent_phone',
    'permanent_mobile': 'permanent_mobile',
    'permanent_email': 'permanent_email',
    'bank_account_number': 'bank_account_number',
    'bank_account_type': 'bank_account_type',
    'bank_name': 'bank_name',
    'bank_branch': 'bank_branch',
    'bank_ifsc': 'bank_ifsc',
    'bank_micr': 'bank_micr',
}

# One2many tables shown on the public profile -> comodel.
DETAIL_LINE_FIELDS = {
    'family_ids': 'hr.employee.family',
    'reference_ids': 'hr.employee.reference',
}

# Never let a line be moved to another employee through the public profile.
_LINE_PROTECTED_KEYS = ('employee_id', 'employee_public_id')


def _details_field(field_class, *args, **kwargs):
    """Non-stored, editable proxy field: never a column of the SQL view, so the
    values are only produced by the access-checked compute below."""
    return field_class(
        *args,
        compute='_compute_personal_details',
        readonly=False,
        **kwargs,
    )


class HrEmployeePublic(models.Model):
    _inherit = 'hr.employee.public'

    # Editable profile photo. In core this related field is readonly, so a
    # regular employee (who only ever sees hr.employee.public in the Employees
    # app) could change their photo nowhere but the avatar menu's "My
    # Preferences". readonly=False makes the widget editable; write() below
    # intercepts the value and stores it on hr.employee with sudo, after the
    # same own-record / HR check as the personal details, so the ORM never
    # tries to write hr.employee as the employee (no ACL there). The form
    # keeps the widget readonly for anybody else's record.
    image_1920 = fields.Image(
        "Image", related='employee_id.image_1920', compute_sudo=True,
        readonly=False)

    can_access_personal_details = fields.Boolean(
        compute='_compute_can_access_personal_details',
        help="True when the current user is this employee, an HR Officer or an administrator.")

    # --- Document Numbers ---
    aadhar_no = _details_field(fields.Char, string='Aadhar No')
    aadhar_copy = _details_field(fields.Binary, string='Aadhar Copy', attachment=False)
    aadhar_copy_filename = _details_field(fields.Char, string='Aadhar Copy Filename')
    pan_no = _details_field(fields.Char, string='PAN No')
    pan_copy = _details_field(fields.Binary, string='PAN Copy', attachment=False)
    pan_copy_filename = _details_field(fields.Char, string='PAN Copy Filename')
    bank_copy = _details_field(fields.Binary, string='Bank Copy', attachment=False)
    bank_copy_filename = _details_field(fields.Char, string='Bank Copy Filename')
    uan_pf_no = _details_field(fields.Char, string='UAN No / PF No')
    father_name = _details_field(fields.Char, string='Name of Father')
    details_birthday = _details_field(fields.Date, string='Date of Birth')
    details_marital = _details_field(
        fields.Selection, selection='_get_details_marital_selection', string='Marital Status')
    date_of_joining = _details_field(fields.Date, string='Date of Joining (DOJ)')
    details_job_title = _details_field(fields.Char, string='Job Title')
    sex = _details_field(
        fields.Selection,
        selection='_get_sex_selection',
        string='Gender',
    )

    # --- Present Address ---
    permanent_same_as_present = _details_field(fields.Boolean, string='Same as Present Address')
    present_address = _details_field(fields.Char, string='Address')
    present_state = _details_field(
        fields.Many2one, 'res.country.state', string='State', domain=INDIA_STATE_DOMAIN)
    present_district = _details_field(fields.Char, string='District')
    present_pin_code = _details_field(fields.Char, string='Pin Code')
    present_mobile = _details_field(fields.Char, string='Mobile No')
    present_email = _details_field(fields.Char, string='Email')
    emergency_contact_no = _details_field(fields.Char, string='Emergency Contact No')

    # --- Permanent Address ---
    permanent_address = _details_field(fields.Char, string='Address')
    permanent_state = _details_field(
        fields.Many2one, 'res.country.state', string='State', domain=INDIA_STATE_DOMAIN)
    permanent_district = _details_field(fields.Char, string='District')
    permanent_pin_code = _details_field(fields.Char, string='Pin Code')
    permanent_phone = _details_field(fields.Char, string='Phone No')
    permanent_mobile = _details_field(fields.Char, string='Mobile No')
    permanent_email = _details_field(fields.Char, string='Email')

    # --- Bank Account Details ---
    bank_account_number = _details_field(fields.Char, string='Bank Account Number')
    bank_account_type = _details_field(
        fields.Selection, selection=BANK_ACCOUNT_TYPES, string='Type of Account')
    bank_name = _details_field(fields.Char, string='Name of Bank')
    bank_branch = _details_field(fields.Char, string='Name of Branch')
    bank_ifsc = _details_field(fields.Char, string='IFSC Code')
    bank_micr = _details_field(fields.Char, string='MICR Code')

    # --- Family / References ---
    # Read as the current user, so the record rules on the line models decide
    # what is returned (own lines for employees, everything for HR / admin).
    family_ids = fields.One2many(
        'hr.employee.family', 'employee_public_id', string='Family Particulars')
    reference_ids = fields.One2many(
        'hr.employee.reference', 'employee_public_id', string='References')

    # ------------------------------------------------------------------
    #  Access helpers
    # ------------------------------------------------------------------
    @api.model
    def _is_personal_details_admin(self):
        user = self.env.user
        return any(user.has_group(group) for group in DETAILS_ADMIN_GROUPS)

    def _filter_personal_details_allowed(self):
        """Records whose personal details the current user may see / edit."""
        if self.env.su or self._is_personal_details_admin():
            return self
        user = self.env.user
        return self.filtered(lambda emp: emp.user_id == user)

    def _check_personal_details_access(self):
        forbidden = self - self._filter_personal_details_allowed()
        if forbidden:
            raise AccessError(_(
                "You can only view or update your own personal details. "
                "Please contact HR to change the details of %s.",
                ', '.join(forbidden.mapped('name'))))

    def _get_details_marital_selection(self):
        return self.env['hr.version']._get_marital_status_selection()

    @api.onchange('permanent_same_as_present', *PRESENT_TO_PERMANENT)
    def _onchange_permanent_same_as_present(self):
        if self.permanent_same_as_present:
            for pres, perm in PRESENT_TO_PERMANENT.items():
                self[perm] = self[pres]

    def _action_view_detail_file(self, field_name):
        """Open an uploaded copy inline in a new browser tab. Served through
        /web/content on hr.employee.public, so the value is produced by the
        access-checked compute (empty for anyone but the owner / HR / admin)."""
        self.ensure_one()
        self._check_personal_details_access()
        filename_field, default_name = VIEWABLE_COPIES[field_name]
        if not self[field_name]:
            raise UserError(_("No file has been uploaded yet."))
        filename = self[filename_field] or default_name
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s/%s/%s?download=false&filename=%s' % (
                self._name, self.id, field_name, url_quote(filename)),
            'target': 'new',
        }

    def action_view_aadhar_copy(self):
        return self._action_view_detail_file('aadhar_copy')

    def action_view_pan_copy(self):
        return self._action_view_detail_file('pan_copy')

    def action_view_bank_copy(self):
        return self._action_view_detail_file('bank_copy')

    @api.model
    def _get_sex_selection(self):
        return self.env['hr.employee']._fields['sex']._description_selection(self.env)

    # ------------------------------------------------------------------
    #  Computes
    # ------------------------------------------------------------------
    @api.depends_context('uid')
    @api.depends('user_id')
    def _compute_can_access_personal_details(self):
        allowed = self._filter_personal_details_allowed()
        for employee in self:
            employee.can_access_personal_details = employee in allowed

    @api.depends_context('uid')
    def _compute_personal_details(self):
        allowed = self._filter_personal_details_allowed()
        # sudo: the user is allowed on these records (own record / HR / admin),
        # but regular employees have no access to the hr.employee model itself.
        employees_sudo = self.env['hr.employee'].sudo().browse(allowed._origin.ids)
        employee_by_id = {emp.id: emp for emp in employees_sudo}
        for public in self:
            employee = employee_by_id.get(public._origin.id)
            for public_fname, employee_fname in PUBLIC_TO_EMPLOYEE_FIELDS.items():
                public[public_fname] = employee[employee_fname] if employee else False

    # ------------------------------------------------------------------
    #  Write: route personal details to hr.employee
    # ------------------------------------------------------------------
    def write(self, vals):
        vals = dict(vals)
        detail_vals = {
            fname: vals.pop(fname) for fname in list(vals)
            if fname in PUBLIC_TO_EMPLOYEE_FIELDS
        }
        line_vals = {
            fname: vals.pop(fname) for fname in list(vals)
            if fname in DETAIL_LINE_FIELDS
        }
        has_image = 'image_1920' in vals
        image = vals.pop('image_1920', False)
        if detail_vals or line_vals or has_image:
            # ACL + record rules (own record for employees, all for HR/admin) ...
            self.check_access('write')
            # ... and an explicit ownership check, independent of the rules.
            self._check_personal_details_access()
            if detail_vals:
                employee_vals = {
                    PUBLIC_TO_EMPLOYEE_FIELDS[fname]: value
                    for fname, value in detail_vals.items()
                }
                # sudo: access checked above; hr.employee constraints still apply.
                self.env['hr.employee'].sudo().browse(self.ids).write(employee_vals)
            for fname, commands in line_vals.items():
                self._write_personal_detail_lines(fname, commands)
            if has_image:
                self._write_profile_image(image)
            self.invalidate_recordset()
        if vals:
            return super().write(vals)
        return True

    def _write_profile_image(self, image):
        """Store a new profile photo on hr.employee (sudo; access was checked
        by write()).

        When the employee changes their OWN photo, the linked user's avatar
        is updated as well, exactly as "My Preferences" would do, so the
        chatter, the top-right avatar and the employee card all agree. HR
        changing somebody else's photo leaves that person's user avatar
        alone, as core does.
        """
        self.env['hr.employee'].sudo().browse(self.ids).write({'image_1920': image})
        own = self.filtered(lambda emp: emp.user_id and emp.user_id == self.env.user)
        if own:
            own.user_id.sudo().write({'image_1920': image})

    def _write_personal_detail_lines(self, fname, commands):
        """Apply x2many commands on family / reference lines as the current
        user, so the ACL and record rules of the line models stay in force."""
        Line = self.env[DETAIL_LINE_FIELDS[fname]]
        for employee in self:
            current = Line.search([('employee_id', '=', employee.id)])

            def _own_lines(ids):
                lines = Line.browse(ids)
                if lines - current:
                    raise AccessError(_("You can only change your own %s.", Line._description))
                return lines

            for command in commands:
                operation = command[0]
                if operation == Command.CREATE:
                    vals = {k: v for k, v in (command[2] or {}).items() if k not in _LINE_PROTECTED_KEYS}
                    vals['employee_id'] = employee.id
                    current |= Line.create(vals)
                elif operation == Command.UPDATE:
                    vals = {k: v for k, v in (command[2] or {}).items() if k not in _LINE_PROTECTED_KEYS}
                    if vals:
                        _own_lines([command[1]]).write(vals)
                elif operation in (Command.DELETE, Command.UNLINK):
                    lines = _own_lines([command[1]])
                    current -= lines
                    lines.unlink()
                elif operation == Command.LINK:
                    _own_lines([command[1]])  # already linked: nothing to do
                elif operation == Command.CLEAR:
                    current.unlink()
                    current = Line
                elif operation == Command.SET:
                    keep = _own_lines(command[2] or [])
                    (current - keep).unlink()
                    current = keep
                else:
                    raise UserError(_("Unsupported operation on %s.", Line._description))
