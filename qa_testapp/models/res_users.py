import logging

from odoo import Command, api, fields, models

_logger = logging.getLogger(__name__)

# External / restricted testers are put in this group. Membership is what
# flips ``qa_bug_only`` on, which in turn narrows every QA record rule down
# to ``qa_bug_project_ids``.
BUG_ONLY_GROUP_XMLID = 'qa_testapp.group_qa_bug_only'

# Job position given to an employee created for a bug-only tester. They are
# not on the payroll, so no existing position fits; the name keeps them
# recognisable in the HR reports the position feeds.
TESTER_JOB_NAME = 'External Tester'


class ResUsers(models.Model):
    _inherit = 'res.users'

    qa_bug_project_ids = fields.Many2many(
        'project.project',
        'qa_bug_only_user_project_rel', 'user_id', 'project_id',
        string='Bug Visibility Projects',
        help="Projects this user is allowed to see bugs, test cases, test plans "
             "and test scenarios for. Only enforced for members of the "
             "'Bug Only (External Tester)' group; ignored for everybody else.",
    )

    # Not stored: the record rules read it once per domain evaluation, and a
    # stored version would have to depend on ``all_group_ids``, which is itself
    # computed and would make the trigger chain fragile.
    qa_bug_only = fields.Boolean(
        string='Bug-Only Access',
        compute='_compute_qa_bug_only',
        compute_sudo=True,
        help="Technical flag read by the QA record rules. True when the user "
             "belongs to the 'Bug Only (External Tester)' group.",
    )

    @api.depends('group_ids')
    def _compute_qa_bug_only(self):
        group = self.env.ref(BUG_ONLY_GROUP_XMLID, raise_if_not_found=False)
        for user in self:
            user.qa_bug_only = bool(group) and group in user.all_group_ids

    def _qa_tester_job(self):
        """The job position for an auto-created tester employee, created on
        first use.

        Scoped to the user's company, because hr.job is. A position shared
        across companies (company_id unset) is reused rather than duplicated.
        """
        self.ensure_one()
        Job = self.env['hr.job'].sudo()
        existing = Job.search([
            ('name', '=ilike', TESTER_JOB_NAME),
            ('company_id', 'in', [self.company_id.id, False]),
        ], limit=1)
        return existing or Job.create({
            'name': TESTER_JOB_NAME,
            'company_id': self.company_id.id,
        })

    def _qa_ensure_employee(self):
        """Give every user in ``self`` an hr.employee record if they lack one.

        hr_timesheet resolves an employee for the user on every timesheet line
        and raises a ValidationError when it cannot find one, so a tester with
        no employee record hits an error on their first save rather than
        anything an administrator would notice first. Creating it alongside
        the group is what makes the timesheet menu actually usable.

        ``job_id`` is mandatory - bt_project_customization redeclares it
        required on hr.version, which hr.employee reaches by delegation - so a
        position is looked up (or created) here instead of relying on a
        default that does not exist.

        An archived employee is reactivated rather than duplicated: two
        employees for one user breaks the lookup hr_timesheet does.

        Never fatal. This runs from a data-load ``<function>`` during module
        upgrades, and an HR-side constraint failing there must not abort the
        upgrade - it logs what to do by hand instead.
        """
        Employee = self.env['hr.employee'].sudo().with_context(active_test=False)
        for user in self:
            existing = Employee.search([
                ('user_id', '=', user.id),
                ('company_id', '=', user.company_id.id),
            ], limit=1)
            if existing:
                if not existing.active:
                    existing.active = True
                continue
            try:
                Employee.create({
                    'name': user.name,
                    'user_id': user.id,
                    'company_id': user.company_id.id,
                    'job_id': user._qa_tester_job().id,
                })
            except Exception:
                _logger.warning(
                    "Could not create an employee for bug-only tester %s. "
                    "Create one by hand under Employees, or their timesheet "
                    "lines will refuse to save.",
                    user.login, exc_info=True,
                )

    @api.model_create_multi
    def create(self, vals_list):
        """Provision the employee for a tester created with the group already
        set - the path an administrator takes in the Users form."""
        users = super().create(vals_list)
        users.filtered('qa_bug_only')._qa_ensure_employee()
        return users

    def write(self, vals):
        """Provision the employee for a tester who is granted the group later.

        Guarded on the group fields because this runs on every write to every
        user, and nothing else can turn somebody into a bug-only tester.
        """
        res = super().write(vals)
        if 'group_ids' in vals or 'all_group_ids' in vals:
            self.filtered('qa_bug_only')._qa_ensure_employee()
        return res

    @api.model
    def _qa_setup_bug_only_user(self, user_xmlid, project_names):
        """Turn a freshly created user into a bug-only tester.

        Two things happen here rather than in the ``<record>`` itself:

        1. The group is granted by ``write`` instead of ``create``. Odoo's
           project module fires ``_onboard_users_into_project`` from
           ``res.users.create`` for any non-share user, and project_todo
           extends it to insert a "Welcome" project.task. During a module
           upgrade that insert runs while the registry is only partially
           built - qa_testapp loads at 176/182, and ft_task_hours_tracker
           loads after it - so project_task.ft_billing_status is not a known
           field yet even though its NOT NULL column already exists, and the
           insert dies on a not-null violation. Creating the user with no
           groups makes it a share user, which skips onboarding entirely;
           granting the group afterwards does not re-trigger it.

        2. The projects are looked up by name, because they are database rows
           with no XML ID to ``ref``.

        Safe to re-run: it is re-applied on every module update, and a project
        that does not exist in this database only logs a warning instead of
        aborting the upgrade.
        """
        user = self.env.ref(user_xmlid, raise_if_not_found=False)
        if not user:
            _logger.warning("QA bug-only setup skipped: user %s not found", user_xmlid)
            return False

        group = self.env.ref(BUG_ONLY_GROUP_XMLID, raise_if_not_found=False)
        if group and group not in user.group_ids:
            # link, not set: never clobber groups an administrator added by hand
            user.sudo().group_ids = [Command.link(group.id)]

        Project = self.env['project.project'].sudo()
        projects = Project.browse()
        missing = set()
        for name in project_names:
            # =ilike, not 'in': project names are free text typed by a human
            # ("MAYORA India" in the live database, not "Mayora India"), and a
            # case-sensitive miss here silently leaves the user seeing nothing.
            match = Project.search([('name', '=ilike', name)], limit=1)
            if match:
                projects |= match
            else:
                missing.add(name)
        if missing:
            _logger.warning(
                "QA bug-only mapping for %s: project(s) %s not found in this database; "
                "map them by hand under Users > Bug Visibility Projects",
                user_xmlid, ', '.join(sorted(missing)),
            )
        if not projects:
            return False

        user.sudo().qa_bug_project_ids = [Command.set(projects.ids)]
        # Belt and braces: the group write above already triggers this, but the
        # group may have been granted by hand before this ever ran.
        user.sudo()._qa_ensure_employee()
        return True
