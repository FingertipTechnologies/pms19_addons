# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Date Extension Request: stage dropdown, computed days, downstream shift,
preponement and the live-gap approval.

Fixtures are created as superuser (TransactionCase env is su), like the
sibling PMS test suites: project creation as a normal user needs groups and
bt_project_customization's "all dates at creation" rule, both of which su
skips. Approvals run as base.user_admin, whom the security data puts in the
approver group. Stages are looked up by NAME (this module does not depend on
the module that defines them); the suite skips itself when the
Implementation stages or the lifecycle date fields are not installed.

A stage's date is the one the project must have REACHED it by (its own
date, as named on the project form): REG -> Regression Date, DEV -> BRD
Approval Date. The fixture requests target REG, so the arithmetic below is
on the Regression Date (today+3) with the BRD Approval Date (today+2) as
the previous step.
"""
from datetime import timedelta
from unittest import SkipTest

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged

from odoo.addons.project_date_extension.models.project_date_extension_request import (
    STAGE_PLANNED_DATE_FIELD,
    _stage_planned_date_field,
)

# (project field, offset in days from today) in step order.
LIFECYCLE = (
    ("date_start", 0),
    ("kick_start_meeting_date", 1),
    ("brd_approval_date", 2),
    ("ft_regression_date", 3),
    ("sandbox_review_date", 4),
    ("uat_start_date", 5),
    ("pl_data_upload_date", 6),
    ("ft_training_date", 7),
    ("go_live_date", 8),
    ("support_start_date", 9),
    ("pl_support_end_date", 10),
    ("date", 60),
)
LATER_THAN_REGRESSION = (
    "sandbox_review_date", "uat_start_date", "pl_data_upload_date",
    "ft_training_date", "go_live_date", "support_start_date",
    "pl_support_end_date", "date",
)
EARLIER_THAN_REGRESSION = ("date_start", "kick_start_meeting_date", "brd_approval_date")


@tagged("post_install", "-at_install")
class TestDateExtensionRequest(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, no_reset_password=True))
        Project = cls.env["project.project"]
        missing = [f for f, _o in LIFECYCLE if f not in Project._fields]
        if missing:
            raise SkipTest("lifecycle date fields not installed: %s" % missing)
        Stage = cls.env["project.project.stage"]
        cls.stage = {}
        for name in ("DISC", "DEV", "REG", "SRV", "UAT", "DATA", "TRA", "SUPPORT", "CLOSED"):
            cls.stage[name] = Stage.search([("name", "=", name)], limit=1)
        if not all(cls.stage.values()):
            raise SkipTest("Implementation stages not installed")
        # KICKOFF is added by ft_project_stage_dates and may be absent; only
        # the test that needs it skips when it is.
        cls.kickoff = Stage.search([("name", "=", "KICKOFF")], limit=1)
        cls.admin = cls.env.ref("base.user_admin")
        approver = cls.env.ref("project_date_extension.group_project_date_extension_approver")
        gfield = "group_ids" if "group_ids" in cls.admin._fields else "groups_id"
        cls.admin.write({gfield: [Command.link(approver.id)]})
        cls.today = fields.Date.today()
        cls.Request = cls.env["project.date.extension.request"]
        cls.ld_regression = cls.env["project.lifecycle.date"].search(
            [("field_name", "=", "ft_regression_date")], limit=1)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _make_project(self, stage="DISC"):
        Project = self.env["project.project"]
        vals = {f: self.today + timedelta(days=o) for f, o in LIFECYCLE}
        vals.update(name="DX Project", stage_id=self.stage[stage].id)
        if "ft_project_type" in Project._fields:
            vals["ft_project_type"] = "implementation"
        if "milestone_ids" in Project._fields:
            vals["milestone_ids"] = [Command.create({"name": "Go Live"})]
        if "module_ids" in Project._fields:
            vals["module_ids"] = [Command.create({"name": "DX Module"})]
        return Project.create(vals)

    def _request(self, project, stage="REG", days=3, **extra):
        """A draft request on ``stage`` moving its planned date by ``days``
        (negative = preponement), as the form would create it."""
        planned = project[_stage_planned_date_field(self.stage[stage])]
        vals = dict(
            project_id=project.id,
            stage_to_extend_id=self.stage[stage].id,
            requested_date=planned + timedelta(days=days) if planned else False,
            reason="because",
        )
        vals.update(extra)
        return self.Request.create(vals)

    def _approve(self, req, new_date=None):
        req.action_submit_request()
        req.with_user(self.admin)._do_approve(new_date=new_date, comment="ok")
        return req

    def _dates(self, project):
        return {f: project[f] for f, _o in LIFECYCLE}

    # ------------------------------------------------------------------
    # mapping
    # ------------------------------------------------------------------
    def test_stage_mapping_helper(self):
        # Each stage pairs with its OWN date (the one it must be reached by),
        # never the next stage's: REG is the Regression Date, DEV the BRD
        # Approval Date.
        self.assertEqual(_stage_planned_date_field(self.stage["REG"]), "ft_regression_date")
        self.assertEqual(_stage_planned_date_field("reg"), "ft_regression_date")
        self.assertEqual(_stage_planned_date_field(self.stage["DEV"]), "brd_approval_date")
        self.assertEqual(_stage_planned_date_field("CLOSED"), "date")
        self.assertIsNone(_stage_planned_date_field("Started"))
        self.assertIsNone(_stage_planned_date_field(False))
        self.assertEqual(STAGE_PLANNED_DATE_FIELD["KICKOFF"], "date_start")
        self.assertEqual(STAGE_PLANNED_DATE_FIELD["SUPPORT"], "support_start_date")
        # Go Live / Support End are nobody's stage date.
        self.assertNotIn("go_live_date", STAGE_PLANNED_DATE_FIELD.values())
        self.assertNotIn("pl_support_end_date", STAGE_PLANNED_DATE_FIELD.values())

    def test_stage_mapping_agrees_with_overdue_milestones(self):
        """The extension map and the Overdue flag read the same date for a
        stage, so the form, the Overdue flag, the request screen and the
        stage report can never disagree on what a stage's date is.

        bt_project_customization is not a dependency of this module, so the
        check goes through project.project._ft_overdue_milestones() (which
        ft_project_lifecycle extends with DATA) and skips when it is absent;
        the constant itself is compared too when it can be imported."""
        Project = self.env["project.project"]
        if not hasattr(Project, "_ft_overdue_milestones"):
            raise SkipTest("bt_project_customization not installed")
        milestones = Project._ft_overdue_milestones()
        self.assertTrue(milestones)
        for key, (fname, _label) in milestones.items():
            self.assertEqual(
                STAGE_PLANNED_DATE_FIELD.get(key.upper()), fname,
                "stage %s: extension map and Overdue flag disagree" % key,
            )
        try:
            from odoo.addons.bt_project_customization.models.project_project import (
                FT_OVERDUE_MILESTONES,
            )
        except ImportError:
            return
        for key, (fname, _label) in FT_OVERDUE_MILESTONES.items():
            self.assertEqual(STAGE_PLANNED_DATE_FIELD.get(key.upper()), fname, key)

    # ------------------------------------------------------------------
    # F1 / F2: stage dropdown and auto-selected date
    # ------------------------------------------------------------------
    def test_allowed_stages_from_disc(self):
        expected = ["DISC", "DEV", "REG", "SRV", "UAT", "DATA", "TRA", "SUPPORT", "CLOSED"]
        project = self._make_project("DISC")
        req = self.Request.new({"project_id": project.id})
        names = req.allowed_stage_ids.mapped("name")
        # Every mapped Implementation stage from DISC on, in lifecycle order
        # (other stages the DB may carry are ignored, not forbidden).
        self.assertEqual([n for n in names if n in expected], expected)
        for name in names:
            self.assertIn(name.upper(), STAGE_PLANNED_DATE_FIELD)
        self.assertNotIn("KICKOFF", [n.upper() for n in names])
        # Stages before the current one are not offered.
        project = self._make_project("REG")
        req = self.Request.new({"project_id": project.id})
        names = req.allowed_stage_ids.mapped("name")
        self.assertNotIn("DISC", names)
        self.assertNotIn("DEV", names)
        self.assertIn("REG", names)
        self.assertIn("CLOSED", names)

    def test_allowed_stages_offers_kickoff(self):
        """A project in KICKOFF may extend KICKOFF itself: its date is the
        Start Date, which create() always defaults, so the stage is offered
        even when the project was created without one."""
        if not self.kickoff:
            raise SkipTest("KICKOFF stage not installed")
        Project = self.env["project.project"]
        vals = {f: self.today + timedelta(days=o) for f, o in LIFECYCLE if f != "date_start"}
        vals.update(name="DX Kickoff", stage_id=self.kickoff.id)
        if "ft_project_type" in Project._fields:
            vals["ft_project_type"] = "implementation"
        if "milestone_ids" in Project._fields:
            vals["milestone_ids"] = [Command.create({"name": "Go Live"})]
        if "module_ids" in Project._fields:
            vals["module_ids"] = [Command.create({"name": "DX Module"})]
        project = Project.create(vals)
        self.assertTrue(project.date_start)
        self.assertEqual(project.stage_id, self.kickoff)
        req = self.Request.new({"project_id": project.id, "stage_to_extend_id": self.kickoff.id})
        self.assertIn("KICKOFF", [n.upper() for n in req.allowed_stage_ids.mapped("name")])
        self.assertEqual(req.date_to_extend_id.field_name, "date_start")
        self.assertEqual(req.current_date, project.date_start)

    def test_stage_without_planned_date_not_offered(self):
        project = self._make_project("DISC")
        # REG's date is the Regression Date; without it REG has nothing to move.
        project.sudo().with_context(skip_date_sequence_check=True).write(
            {"ft_regression_date": False})
        req = self.Request.new({"project_id": project.id})
        self.assertNotIn("REG", req.allowed_stage_ids.mapped("name"))
        self.assertIn("SRV", req.allowed_stage_ids.mapped("name"))
        with self.assertRaises(ValidationError):
            self._request(project, "REG", requested_date=self.today + timedelta(days=20))

    def test_choosing_stage_sets_date_and_current(self):
        project = self._make_project("DISC")
        req = self._request(project, "REG", days=3)
        self.assertEqual(req.stage_id, self.stage["DISC"])
        # REG's date is the Regression Date (the date REG must be reached by).
        self.assertEqual(req.date_to_extend_id, self.ld_regression)
        self.assertEqual(req.current_date, project.ft_regression_date)
        # F3 / F4
        self.assertEqual(req.requested_date, project.ft_regression_date + timedelta(days=3))
        self.assertEqual(req.extension_days, 3)
        self.assertFalse(req.is_preponement)
        self.assertEqual(req.delay_days, 3)
        # F5: the preview lists every later set date, shifted by 3.
        html = req.downstream_impact
        self.assertIn("Sandbox Review Date", html)
        self.assertIn("Closed Date", html)
        self.assertNotIn("BRD Approval Date", html)

    def test_onchange_stage_in_form(self):
        project = self._make_project("DISC")
        form_vals = {"project_id": project.id, "stage_to_extend_id": self.stage["UAT"].id}
        req = self.Request.new(form_vals)
        # UAT's date is the UAT Start Date, not the (next) Data Upload Date.
        self.assertEqual(req.date_to_extend_id.field_name, "uat_start_date")
        self.assertEqual(req.current_date, project.uat_start_date)
        form_vals["stage_to_extend_id"] = self.stage["DEV"].id
        req = self.Request.new(form_vals)
        self.assertEqual(req.date_to_extend_id.field_name, "brd_approval_date")
        self.assertEqual(req.current_date, project.brd_approval_date)

    def test_same_date_refused(self):
        project = self._make_project("DISC")
        with self.assertRaises(ValidationError):
            self._request(project, "REG", requested_date=project.ft_regression_date)

    # ------------------------------------------------------------------
    # approval: downstream shift, no double counting
    # ------------------------------------------------------------------
    def test_approval_shifts_later_dates(self):
        project = self._make_project("DISC")
        before = self._dates(project)
        req = self._approve(self._request(project, "REG", days=3))
        self.assertEqual(req.state, "approved")
        self.assertEqual(project.ft_regression_date, before["ft_regression_date"] + timedelta(days=3))
        for f in LATER_THAN_REGRESSION:
            self.assertEqual(project[f], before[f] + timedelta(days=3), f)
        for f in EARLIER_THAN_REGRESSION:
            self.assertEqual(project[f], before[f], f)
        self.assertEqual(req.extension_days, 3)
        self.assertEqual(req.current_date, before["ft_regression_date"])

    def test_second_request_counts_only_its_own_days(self):
        project = self._make_project("DISC")
        first = self._approve(self._request(project, "REG", days=3))
        after_first = project.ft_regression_date
        second = self._request(project, "REG", days=5)
        self.assertEqual(second.current_date, after_first)
        self.assertEqual(second.extension_days, 5)
        self._approve(second)
        self.assertEqual(project.ft_regression_date, after_first + timedelta(days=5))
        total = sum(self.Request.search(
            [("project_id", "=", project.id), ("state", "=", "approved")]
        ).mapped("delay_days"))
        self.assertEqual(total, 8)
        self.assertEqual(first.extension_days, 3)

    def test_approver_may_adjust_date(self):
        project = self._make_project("DISC")
        before = self._dates(project)
        req = self._request(project, "REG", days=3)
        self._approve(req, new_date=before["ft_regression_date"] + timedelta(days=10))
        self.assertEqual(req.extension_days, 10)
        self.assertEqual(project.ft_regression_date, before["ft_regression_date"] + timedelta(days=10))
        self.assertEqual(project.date, before["date"] + timedelta(days=10))

    # ------------------------------------------------------------------
    # F6: preponement
    # ------------------------------------------------------------------
    def test_preponement_moves_only_selected_date(self):
        project = self._make_project("DISC")
        before = self._dates(project)
        # Regression is today+3, BRD Approval today+2: moving to today+2 is allowed.
        req = self._request(project, "REG", days=-1)
        self.assertTrue(req.is_preponement)
        self.assertEqual(req.extension_days, -1)
        self.assertEqual(req.delay_days, 0)
        self.assertIn("No later dates will change", req.downstream_impact)
        self._approve(req)
        self.assertEqual(project.ft_regression_date, before["ft_regression_date"] - timedelta(days=1))
        for f in LATER_THAN_REGRESSION + EARLIER_THAN_REGRESSION:
            self.assertEqual(project[f], before[f], f)
        self.assertEqual(req.state, "approved")

    def test_preponement_before_previous_date_refused_at_submit(self):
        project = self._make_project("DISC")
        # today+1 is before BRD Approval (today+2).
        req = self._request(project, "REG", days=-2)
        self.assertTrue(req.is_preponement)
        with self.assertRaisesRegex(ValidationError, "previous planned date"):
            req.action_submit_request()
        self.assertEqual(req.state, "draft")

    def test_preponement_before_previous_date_refused_at_approval(self):
        project = self._make_project("DISC")
        req = self._request(project, "REG", days=-1)  # today+2 == BRD date: fine
        req.action_submit_request()
        # BRD Approval moves after the requested date in the meantime.
        project.sudo().with_context(skip_date_sequence_check=True).write(
            {"brd_approval_date": self.today + timedelta(days=3)})
        before = self._dates(project)
        with self.assertRaises(ValidationError):
            req.with_user(self.admin)._do_approve(comment="ok")
        self.assertEqual(self._dates(project), before)

    # ------------------------------------------------------------------
    # stale gap: the shift is measured against the LIVE project date
    # ------------------------------------------------------------------
    def test_approval_uses_live_date(self):
        project = self._make_project("DISC")
        before = self._dates(project)
        req = self._request(project, "REG", days=3)  # requested = today+6
        req.action_submit_request()
        # Regression is moved by 2 days behind this request's back.
        project.sudo().with_context(skip_date_sequence_check=True).write(
            {"ft_regression_date": before["ft_regression_date"] + timedelta(days=2)})
        req.with_user(self.admin)._do_approve(comment="ok")
        # The selected date lands on the requested date...
        self.assertEqual(project.ft_regression_date, before["ft_regression_date"] + timedelta(days=3))
        # ...and the later dates move by the LIVE gap (1 day), not the stale 3.
        for f in LATER_THAN_REGRESSION:
            self.assertEqual(project[f], before[f] + timedelta(days=1), f)
        self.assertEqual(req.current_date, before["ft_regression_date"] + timedelta(days=2))
        self.assertEqual(req.extension_days, 1)
        self.assertEqual(req.delay_days, 1)

    def test_live_date_can_turn_request_into_preponement(self):
        project = self._make_project("DISC")
        before = self._dates(project)
        req = self._request(project, "REG", days=1)  # requested = today+4
        req.action_submit_request()
        project.sudo().with_context(skip_date_sequence_check=True).write(
            {"ft_regression_date": before["ft_regression_date"] + timedelta(days=2)})  # today+5
        req.with_user(self.admin)._do_approve(comment="ok")
        self.assertTrue(req.is_preponement)
        self.assertEqual(req.extension_days, -1)
        self.assertEqual(project.ft_regression_date, before["ft_regression_date"] + timedelta(days=1))
        for f in LATER_THAN_REGRESSION:
            self.assertEqual(project[f], before[f], f)

    # ------------------------------------------------------------------
    # legacy: a request raised by date only still works
    # ------------------------------------------------------------------
    def test_legacy_date_only_request(self):
        project = self._make_project("DISC")
        before = self._dates(project)
        req = self.Request.create({
            "project_id": project.id,
            "date_to_extend_id": self.ld_regression.id,
            "requested_date": before["ft_regression_date"] + timedelta(days=2),
            "reason": "legacy",
        })
        self.assertFalse(req.stage_to_extend_id)
        self.assertEqual(req.current_date, before["ft_regression_date"])
        self.assertEqual(req.extension_days, 2)
        self._approve(req)
        self.assertEqual(project.date, before["date"] + timedelta(days=2))

    def test_rejection_keeps_dates(self):
        project = self._make_project("DISC")
        before = self._dates(project)
        req = self._request(project, "REG", days=3)
        req.action_submit_request()
        req.with_user(self.admin)._do_reject(comment="no")
        self.assertEqual(req.state, "rejected")
        self.assertEqual(self._dates(project), before)
