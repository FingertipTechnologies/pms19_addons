# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from ..models.mail_thread import TICKET_NO_REGEX


EMAIL_TEMPLATE = """Return-Path: <{email_from}>
To: support@fingertipplus.com
Message-ID: {msg_id}
Date: Fri, 30 Oct 2026 12:00:00 +0000
From: {email_from}
Subject: {subject}
MIME-Version: 1.0
Content-Type: text/plain; charset=utf-8

{body}
"""


class TestEmailToTicket(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.customer_user = cls.env['res.partner'].create({
            'name': 'Test Customer',
            'email': 'customer@example.com',
        })

    def test_01_ticket_no_regex(self):
        """Test the ticket number extraction regex for various email subject formats."""
        # Scenario 1: No ticket number
        match = TICKET_NO_REGEX.search("Unable to Login to Portal")
        self.assertIsNone(match)

        # Scenario 2: Bracketed ticket number
        match = TICKET_NO_REGEX.search("Re: [TKT-000123] Unable to Login to Portal")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1).upper(), "TKT-000123")

        # Notification template format
        match = TICKET_NO_REGEX.search("Re: Ticket Created TKT-000123 Fingertip PMS")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1).upper(), "TKT-000123")

        # Scenario 3: Invalid/Non-existent ticket number format
        match = TICKET_NO_REGEX.search("Re: [TKT-999999] Login Issue")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1).upper(), "TKT-999999")

        # Unrelated text containing TKT prefix without numbers
        match = TICKET_NO_REGEX.search("TKT without numbers or TKT-abc")
        self.assertIsNone(match)

    def test_02_scenario_1_create_new_ticket(self):
        """Scenario 1: Incoming email with no ticket number creates a new ticket."""
        email_content = EMAIL_TEMPLATE.format(
            email_from="customer@example.com",
            msg_id="<test-msg-001@example.com>",
            subject="Unable to Login to Portal",
            body="Hello support, I cannot log into my client portal account. Please help.",
        )

        initial_count = self.env['ft.helpdesk.ticket'].search_count([])

        res_id = self.env['mail.thread'].message_process(
            model='ft.helpdesk.ticket',
            message=email_content.encode('utf-8'),
            save_original=False,
            strip_attachments=False,
        )

        self.assertTrue(res_id, "message_process should return the created ticket ID")
        self.assertEqual(
            self.env['ft.helpdesk.ticket'].search_count([]),
            initial_count + 1,
            "A new ticket should be created in the database"
        )

        ticket = self.env['ft.helpdesk.ticket'].browse(res_id)
        self.assertEqual(ticket.name, "Unable to Login to Portal")
        self.assertEqual(ticket.customer_id.email, "customer@example.com")
        self.assertEqual(ticket.channel, "email")
        self.assertEqual(ticket.state, "new")
        self.assertTrue(ticket.ticket_no.startswith("TKT-"), "Ticket number should have TKT- prefix")
        self.assertIn("cannot log into my client portal", ticket.description)

    def test_03_scenario_2_update_existing_ticket_chatter(self):
        """Scenario 2: Incoming email with an existing ticket number updates Chatter."""
        # Create an initial ticket
        ticket = self.env['ft.helpdesk.ticket'].create({
            'name': 'Unable to Login to Portal',
            'customer_id': self.customer_user.id,
            'state': 'pending_customer',
        })
        ticket_no = ticket.ticket_no
        self.assertTrue(ticket_no and ticket_no.startswith("TKT-"))

        initial_ticket_count = self.env['ft.helpdesk.ticket'].search_count([])
        initial_msg_count = len(ticket.message_ids)

        # Incoming reply containing the ticket number in subject
        reply_email = EMAIL_TEMPLATE.format(
            email_from="customer@example.com",
            msg_id="<test-reply-002@example.com>",
            subject=f"Re: [{ticket_no}] Unable to Login to Portal",
            body="Here is additional information regarding the login error.",
        )

        res_id = self.env['mail.thread'].message_process(
            model='ft.helpdesk.ticket',
            message=reply_email.encode('utf-8'),
            save_original=False,
            strip_attachments=False,
        )

        # Ensure no duplicate ticket was created
        self.assertEqual(res_id, ticket.id)
        self.assertEqual(
            self.env['ft.helpdesk.ticket'].search_count([]),
            initial_ticket_count,
            "No new ticket should be created for an existing ticket reply"
        )

        # Verify message was posted to existing ticket's Chatter
        ticket.invalidate_recordset()
        self.assertGreater(len(ticket.message_ids), initial_msg_count)
        latest_msg = ticket.message_ids[0]
        self.assertIn("additional information regarding the login error", latest_msg.body)
        self.assertEqual(latest_msg.email_from, "customer@example.com")

        # Verify ticket was automatically reopened from pending_customer to open
        self.assertEqual(ticket.state, 'open')
        self.assertTrue(ticket.last_customer_reply_at)

    def test_04_scenario_3_invalid_ticket_number_creates_new_ticket(self):
        """Scenario 3: Incoming email with non-existent ticket number creates a new ticket."""
        initial_count = self.env['ft.helpdesk.ticket'].search_count([])

        invalid_ref_email = EMAIL_TEMPLATE.format(
            email_from="customer@example.com",
            msg_id="<test-invalid-003@example.com>",
            subject="Re: [TKT-999999] Login Issue",
            body="I am referencing a ticket number that does not exist.",
        )

        res_id = self.env['mail.thread'].message_process(
            model='ft.helpdesk.ticket',
            message=invalid_ref_email.encode('utf-8'),
            save_original=False,
            strip_attachments=False,
        )

        self.assertTrue(res_id)
        self.assertEqual(
            self.env['ft.helpdesk.ticket'].search_count([]),
            initial_count + 1,
            "A new ticket should be created when ticket number does not exist"
        )

        new_ticket = self.env['ft.helpdesk.ticket'].browse(res_id)
        self.assertNotEqual(new_ticket.ticket_no, "TKT-999999")
        self.assertEqual(new_ticket.name, "Re: [TKT-999999] Login Issue")
        self.assertIn("referencing a ticket number that does not exist", new_ticket.description)

    def test_05_duplicate_prevention(self):
        """Test that re-processing the same email (identical Message-ID) is safely discarded."""
        email_content = EMAIL_TEMPLATE.format(
            email_from="customer@example.com",
            msg_id="<test-unique-id-999@example.com>",
            subject="First Submission",
            body="Unique submission content.",
        )

        res_1 = self.env['mail.thread'].message_process(
            model='ft.helpdesk.ticket',
            message=email_content.encode('utf-8'),
        )
        self.assertTrue(res_1)

        # Processing the exact same email again
        res_2 = self.env['mail.thread'].message_process(
            model='ft.helpdesk.ticket',
            message=email_content.encode('utf-8'),
        )
        # Duplicate Message-ID should be ignored
        self.assertFalse(res_2, "Duplicate Message-ID should not create or update anything")

    def test_06_customer_team_auto_assignment(self):
        """Test that an incoming email automatically assigns the customer's configured Support Team."""
        # Create a test team with default assignee
        test_team = self.env['ft.helpdesk.team'].create({
            'name': 'Customer Care Dedicated Team',
            'auto_assign_mode': 'manual',
            'default_assignee_id': self.env.user.id,
        })

        # Assign team to customer
        self.customer_user.write({'helpdesk_team_id': test_team.id})

        email_content = EMAIL_TEMPLATE.format(
            email_from="customer@example.com",
            msg_id="<test-team-assign-001@example.com>",
            subject="Billing Question",
            body="I have a question about my invoice.",
        )

        res_id = self.env['mail.thread'].message_process(
            model='ft.helpdesk.ticket',
            message=email_content.encode('utf-8'),
            save_original=False,
            strip_attachments=False,
        )

        self.assertTrue(res_id, "Ticket should be created")
        ticket = self.env['ft.helpdesk.ticket'].browse(res_id)
        self.assertEqual(ticket.team_id, test_team, "Ticket should have customer's support team assigned")
        self.assertEqual(ticket.assigned_user_id, self.env.user, "Ticket should have team's default assignee assigned")

