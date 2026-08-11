# FT Helpdesk for Odoo 18 — Complete User Guide

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Backend Workflow (Agents & Admins)](#2-backend-workflow-agents--admins)
3. [Ticket Lifecycle & States](#3-ticket-lifecycle--states)
4. [Team Management & Assignment](#4-team-management--assignment)
5. [SLA Policies & Breach Handling](#5-sla-policies--breach-handling)
6. [Automation — Macros & Triggers](#6-automation--macros--triggers)
7. [Knowledge Base](#7-knowledge-base)
8. [Reporting & Analytics](#8-reporting--analytics)
9. [Customer Portal — Complete Guide](#9-customer-portal--complete-guide)
10. [Configuration Reference](#10-configuration-reference)
11. [Default Seed Data](#11-default-seed-data)
12. [URL Reference](#12-url-reference)

---

## 1. System Overview

FT Helpdesk is a modular helpdesk/support ticket system built for Odoo 18. It consists of 7 modules:

| Module | Purpose |
|--------|---------|
| **ft_helpdesk_core** | Tickets, teams, categories, tags, close reasons, canned responses, business hours |
| **ft_helpdesk_portal** | Customer-facing portal for ticket submission, tracking, and conversation |
| **ft_helpdesk_sla** | SLA policies, deadline tracking, breach detection |
| **ft_helpdesk_knowledge** | Knowledge base articles and categories (public-facing) |
| **ft_helpdesk_automation** | Macros (one-click agent actions) and triggers (event-driven automation) |
| **ft_helpdesk_reporting** | Pivot/graph analytics for ticket performance metrics |
| **ft_helpdesk_ui** | Email templates and frontend styling |

### User Roles

| Role | Odoo Group | Permissions |
|------|-----------|-------------|
| **Agent** | FT Helpdesk / Agent | View and manage tickets assigned to them, use macros, post replies |
| **Team Lead** | FT Helpdesk / Team Lead | All agent permissions + manage SLA policies, view team reports |
| **Administrator** | FT Helpdesk / Administrator | Full access: configuration, automation, all tickets, settings |
| **Customer** | Portal User (Odoo default) | Submit tickets, view own tickets, reply, close/reopen (if enabled) |

---

## 2. Backend Workflow (Agents & Admins)

### 2.1 Navigating the Helpdesk

After installation, the **Helpdesk** app appears in the top navigation bar. It contains:

- **Tickets** — All Tickets, My Tickets, Unassigned
- **Teams** — Team dashboard (kanban and list)
- **Knowledge Base** — KB articles and categories (if installed)
- **Reporting** — Ticket analysis (if installed)
- **Configuration** — Settings, Teams, Categories, Subcategories, Ticket Types, Dynamic Fieldsets, Tags, Close Reasons, Canned Responses, Business Hours

### 2.2 Creating a Ticket (Backend)

1. Go to **Helpdesk > Tickets > All Tickets**
2. Click **New**
3. Fill in:
   - **Subject** (required) — brief description of the issue
   - **Customer** — select the customer contact
   - **Team** — assign to a support team
   - **Assigned To** — assign to a specific agent (or leave empty for auto-assignment)
   - **Category / Subcategory** — classify the issue
   - **Ticket Type** — Question, Incident, Service Request, Feedback
   - **Priority** — Low, Normal, High, Urgent
   - **Description** — detailed issue description
4. Click **Save** — the ticket gets an auto-generated number (e.g., `TKT-000001`)

### 2.3 Working a Ticket

Once a ticket is open, an agent can:

| Action | How | Effect |
|--------|-----|--------|
| **Assign to Me** | Click "Assign to Me" button | Sets you as the assignee; moves New tickets to In Progress |
| **Reply to Customer** | Post a message in the chatter (Log note = internal, Send message = public) | First public reply stamps `first_response_at` for SLA tracking |
| **Request Info** | Click "Request Info" button or set state to "Pending Customer" | Moves ticket to Pending Customer — customer sees "Pending Your Reply" |
| **Mark Pending Internal** | Status bar button | Indicates the ticket is blocked on an internal dependency |
| **Resolve** | Click "Resolved" on the status bar | Stamps `resolved_at`, moves to Resolved state |
| **Close** | Click "Close" button | Opens a wizard requiring a close reason and optional resolution summary |
| **Cancel** | Click "Cancel" button | Opens a wizard with cancel-specific reasons (Duplicate, Spam, Invalid) |
| **Reopen** | Click "Reopen" button | Moves ticket back to In Progress, clears all terminal timestamps |
| **Escalate** | Click "Escalate" button | Forces priority to Urgent, increments escalation level, notifies team leader |
| **Apply Macro** | Select a macro from the macro menu | Applies preconfigured bulk actions (state change, assign, tag, reply) |

### 2.4 Bulk Operations

From the ticket list view, select multiple tickets using checkboxes:

- **Bulk Assign** — Opens a wizard to assign all selected tickets to a user/team
- **Bulk Close** — Opens the close wizard for all selected tickets

### 2.5 Canned Responses

Pre-written templates agents can use for quick replies:

| Shortcut | Name | What it says |
|----------|------|-------------|
| `/greet` | Greeting | "Thank you for contacting us..." |
| `/moreinfo` | Request More Information | "To help resolve your issue, could you provide..." |
| `/close` | Closing Message | "Your ticket has been resolved..." |

Canned responses support **placeholders** that auto-fill:
- `{{ticket.ticket_no}}` — Ticket number
- `{{ticket.customer_id.name}}` — Customer name
- `{{ticket.assigned_user_id.name}}` — Agent name
- `{{ticket.team_id.name}}` — Team name

Create new canned responses at **Configuration > Canned Responses**.

---

## 3. Ticket Lifecycle & States

### 3.1 State Definitions

| State | Label | Color | Meaning |
|-------|-------|-------|---------|
| `new` | New | Grey | Freshly created, not yet worked on |
| `open` | In Progress | Blue | An agent is actively working the ticket |
| `pending_customer` | Pending Customer | Yellow | Waiting for the customer to reply |
| `pending_internal` | Pending Internal | Orange | Blocked on an internal dependency |
| `resolved` | Resolved | Green | Issue resolved, awaiting formal close |
| `closed` | Closed | Teal | Formally closed with a reason |
| `cancelled` | Cancelled | Red | Cancelled (spam, duplicate, invalid) |

### 3.2 State Flow Diagram

```
                        +---> Pending Customer ---+
                        |    (waiting on customer) |
                        |                          |
  New ---> In Progress -+---> Pending Internal  ---+---> Resolved ---> Closed
   |          ^         |    (internal blocker)    |        |
   |          |         |                          |        |
   |          +--------- <--- (customer replies) --+        |
   |          |                                             |
   |          +------------- Reopen <-----------------------+
   |                                                        |
   +---> Cancelled <--- (cancel wizard) ------- any open state
```

### 3.3 Automatic State Transitions

| Event | Automatic Transition |
|-------|---------------------|
| Ticket assigned (via assign button, wizard, or round-robin) | New → In Progress |
| Customer replies (portal message) | Pending Customer → In Progress |
| Auto-close cron (daily, configurable) | Resolved → Closed (after N days) |

### 3.4 Timestamps Tracked

| Timestamp | When it's set |
|-----------|--------------|
| `create_date` | Ticket creation |
| `first_response_at` | First public reply by an agent |
| `last_agent_reply_at` | Every public reply by an agent |
| `last_customer_reply_at` | Every reply by the customer |
| `resolved_at` | State changes to Resolved (or Closed if never resolved first) |
| `closed_at` | State changes to Closed |
| `cancelled_at` | State changes to Cancelled |

---

## 4. Team Management & Assignment

### 4.1 Creating a Team

Go to **Configuration > Teams > New**:

- **Name** — Team name (e.g., "Tier 1 Support")
- **Team Leader** — User who receives escalation notifications
- **Members** — Users who belong to the team
- **Default Assignee** — Fallback assignee when no other rule applies
- **Auto-Assignment Mode**:
  - **Manual** (default) — Agents pick up tickets manually
  - **Round Robin** — Tickets are automatically distributed to team members in sequence
- **Portal Enabled** — If checked, customers can submit tickets to this team from the portal

### 4.2 Round-Robin Assignment

When `Auto-Assignment Mode = Round Robin`:

1. A new ticket is created and assigned to the team
2. The system reads the team's `last_assigned_index` (persisted counter)
3. Selects the member at position `index % number_of_members`
4. Assigns the ticket to that member
5. Increments the counter for the next ticket

The counter persists across server restarts, ensuring fair distribution.

### 4.3 Escalation

When a ticket is escalated (manually or via SLA breach):

1. `is_escalated` flag is set to True
2. `escalation_level` increments by 1 (supports multi-level)
3. Priority is forced to **Urgent**
4. An internal note is posted
5. The team leader receives an Odoo activity (to-do) notification

---

## 5. SLA Policies & Breach Handling

### 5.1 Creating an SLA Policy

Go to **Helpdesk > SLA Policies > New**:

| Field | Description |
|-------|-------------|
| **Name** | Policy name (e.g., "Urgent — 1h Response, 4h Resolution") |
| **Team** | Apply only to this team (leave empty for all) |
| **Minimum Priority** | Minimum priority level to match (e.g., "High" matches High and Urgent) |
| **Category** | Apply only to this category (leave empty for all) |
| **Ticket Type** | Apply only to this type (leave empty for all) |
| **First Response Hours** | Target hours for first agent response (default: 4) |
| **Resolution Hours** | Target hours for full resolution (default: 24) |
| **Business Hours** | Use business hours schedule for deadline computation (leave empty for 24/7) |
| **Escalate on Breach** | Automatically escalate when breached (default: Yes) |
| **Notify Users** | Users to notify when breached |

### 5.2 How SLA Matching Works

When a ticket is created:

1. All active SLA policies are evaluated in **sequence order**
2. Each policy's criteria (team, priority, category, type) are checked against the ticket
3. The **first matching policy** is applied (remaining policies are skipped)
4. An SLA Status record is created with computed deadlines

### 5.3 SLA States

| State | Meaning | Condition |
|-------|---------|-----------|
| **On Track** | Everything is fine | More than 25% of time remaining |
| **At Risk** | Running low on time | Less than 25% of time remaining on either deadline |
| **Breached** | Deadline has passed | First response or resolution deadline exceeded |
| **Completed** | All SLA targets met | Both first response and resolution done on time |

### 5.4 Breach Detection (Cron)

A scheduled job runs **every 5 minutes**:

1. Finds all SLA status records where a deadline has passed but the milestone is incomplete
2. Marks the appropriate breach flag (`first_response_breached` or `resolution_breached`)
3. Posts an internal note on the ticket
4. If `escalate_on_breach = True`, triggers escalation
5. If `notify_user_ids` is set, creates activity notifications

### 5.5 Auto-Close Cron (Daily)

A daily cron checks for resolved tickets older than the configured threshold:

1. Reads the `Auto-Close Resolved Tickets` setting (in days, 0 = disabled)
2. Finds all tickets in Resolved state where `resolved_at` is older than the cutoff
3. Moves them to Closed and posts a notification note

---

## 6. Automation — Macros & Triggers

### 6.1 Macros (Agent-Initiated)

Macros are one-click action bundles that agents apply to tickets. Create them at **Configuration > Macros**.

A macro can perform any combination of:

| Action | Example |
|--------|---------|
| Set state | Move to "Pending Customer" |
| Set priority | Escalate to "Urgent" |
| Set assignee | Reassign to senior agent |
| Add tags | Add "VIP Customer" tag |
| Remove tags | Remove "Needs Triage" tag |
| Post a reply | Send a canned message (public or internal note) |

Macros can be scoped to specific teams or left available for all.

### 6.2 Triggers (Event-Driven)

Triggers fire automatically in response to ticket events. Create them at **Configuration > Triggers**.

**Trigger Events:**

| Event | Fires When |
|-------|-----------|
| **Ticket Created** | A new ticket is created |
| **Status Changed** | A ticket's state changes |
| **SLA Breach** | An SLA deadline is breached |
| **Customer Reply** | A customer posts a reply |

**Domain Filter:** Each trigger has an optional domain that controls which tickets it applies to. Examples:
- `[('team_id.name', '=', 'Support')]` — only tickets for the Support team
- `[('priority', '>=', '2')]` — only High or Urgent tickets
- `[('channel', '=', 'portal')]` — only portal-submitted tickets

**Available Actions** (same as macros):
- Set state, priority, assignee
- Add/remove tags
- Post a reply (public or internal)
- Notify users (schedule activity)

---

## 7. Knowledge Base

### 7.1 Managing Articles (Backend)

Go to **Helpdesk > Knowledge Base**:

- **KB Categories** — Organize articles into categories with icons
- **KB Articles** — Create articles with title, slug (URL), summary, body (rich HTML), and keywords

Article fields:
| Field | Description |
|-------|-------------|
| **Title** | Article title |
| **Slug** | URL-friendly identifier (e.g., `how-to-reset-password`) |
| **Category** | KB category this article belongs to |
| **Summary** | Short description shown in lists |
| **Body** | Full article content (HTML editor) |
| **Keywords** | Comma-separated keywords for search |
| **Published** | Toggle visibility on the portal |
| **View Count** | Auto-incremented when the article is viewed |
| **Helpful Score** | Updated by customer votes (thumbs up/down) |

### 7.2 KB on the Portal

Customers access the Knowledge Base at `/my/support/kb` (publicly accessible — no login required).

Features:
- **Category browsing** — Grid of KB categories with article counts
- **Full-text search** — Searches title, summary, keywords, and body
- **Article detail** — Full article with view counter and "Was this helpful?" voting
- **Related articles** — Sidebar shows up to 5 related articles from the same category
- **Ticket creation link** — "Still need help? Create a Ticket" on every article page

### 7.3 KB Suggestions During Ticket Creation

When a customer types a subject on the ticket creation form, the system automatically suggests relevant KB articles. This is powered by an AJAX search endpoint and can be enabled/disabled in Settings.

---

## 8. Reporting & Analytics

### 8.1 Accessing Reports

Go to **Helpdesk > Reporting > Ticket Analysis**.

The report is available in **Pivot**, **Graph**, and **List** views.

### 8.2 Available Dimensions (Group By)

| Dimension | Description |
|-----------|-------------|
| Team | Support team |
| Assigned To | Agent handling the ticket |
| Category | Ticket category |
| Ticket Type | Type classification |
| Priority | Low / Normal / High / Urgent |
| State | Current ticket state |
| Channel | Portal / Email / Internal / API |
| Customer | Customer contact |
| Company | Multi-company support |
| Create Date | Ticket creation date (supports monthly/weekly grouping) |

### 8.3 Available Measures

| Measure | Description |
|---------|-------------|
| **First Response Hours** | Average hours from creation to first agent response |
| **Resolution Hours** | Average hours from creation to resolution |
| **SLA Breached** | Count/percentage of tickets with SLA breaches |
| **Escalated** | Count/percentage of escalated tickets |
| **Count** | Total number of tickets |

### 8.4 Example Reports

- **Average first response time by team** — Pivot: Group by Team, Measure = First Response Hours
- **SLA breach rate by priority** — Pivot: Group by Priority, Measure = SLA Breached (count)
- **Tickets created per week** — Graph (line chart): Group by Create Date (week), Measure = Count
- **Resolution time by category** — Graph (bar chart): Group by Category, Measure = Resolution Hours

---

## 9. Customer Portal — Complete Guide

### 9.1 Accessing the Portal

Customers need to be **Portal Users** in Odoo. To invite a customer:

1. Go to **Settings > Users & Companies > Users**
2. Click **Invite Portal Users** (or set an existing contact as Portal User)
3. The customer receives an email with login credentials

### 9.2 Portal Home

After logging in, the customer goes to **My Account** (`/my`). They will see a **"Support Tickets"** card with their ticket count. Clicking it goes to `/my/support`.

### 9.3 Support Dashboard (`/my/support`)

The support home page shows:

- **Quick Actions** — Three cards:
  - "Create a Ticket" → `/my/support/ticket/new`
  - "My Tickets" → `/my/support/tickets`
  - "Knowledge Base" → `/my/support/kb`
- **Stats** — Four counters: Open Tickets, Awaiting Your Reply, Resolved, Total
- **Recent Tickets** — Last 5 tickets with number, subject, state badge, priority, and date

### 9.4 Creating a Ticket (`/my/support/ticket/new`)

The creation form is a multi-step layout:

**Step 1 — Categorize Your Request:**
- **Category** (dropdown) — Selecting a category may load subcategories via AJAX
- **Subcategory** (dropdown, appears dynamically)
- **Ticket Type** — Selecting a type may load additional dynamic fields via AJAX
- **Priority** — Low, Normal (default), High, Urgent

**Step 2 — Describe Your Issue:**
- **Subject** (required) — As the customer types, KB article suggestions may appear
- **Description** (required) — Detailed description

**Step 3 — Additional Information** (appears dynamically based on ticket type):
- Custom fields defined by the ticket type's fieldset (text, selection, etc.)

**Attachments:**
- Upload multiple files (jpg, png, pdf, doc, xls, txt, csv, zip — max 10MB each)

Click **"Submit Ticket"** → redirected to the ticket detail page with a success message.

### 9.5 Viewing Tickets (`/my/support/tickets`)

A paginated list (20 per page) with:

**Filters:**
| Filter | Shows |
|--------|-------|
| All | All tickets |
| Open | Not closed or cancelled |
| Pending My Reply | Tickets awaiting customer's response |
| Resolved | Resolved or closed tickets |
| Urgent | Urgent priority tickets only |

**Search:** Search by All fields, Subject, Ticket #, or Description.

**Sort:** Newest, Oldest, Priority, Status, Subject.

Each ticket shows: number, subject, state badge, priority badge, category, assignee, date.

### 9.6 Ticket Detail (`/my/support/ticket/<id>`)

**Main area (left column):**
- Ticket number, subject, state badge, priority badge
- Full description
- **Action buttons** (if enabled in Settings):
  - "Close Ticket" — closes the ticket from the portal (with confirmation dialog)
  - "Reopen Ticket" — reopens a resolved/closed ticket
- **Conversation thread** — All public messages between the customer and agents. Internal notes are NOT visible to customers. Messages show:
  - Circular avatar (blue for customer, green for agent with "Support" badge)
  - Author name, timestamp, message body, attachments
- **Reply form** (only visible if ticket is not closed/cancelled):
  - Text area for the reply
  - File attachment upload
  - "Send Reply" button

**Sidebar (right column):**
- Ticket details table: Status, Priority, Ticket #, Created date, Category, Type, Assignee, Team, Resolved date
- Attachments list with download links
- "Back to My Tickets" button

### 9.7 Portal Actions

| Action | URL | When Available |
|--------|-----|---------------|
| Reply to ticket | POST `/my/support/ticket/<id>/reply` | Ticket is not closed/cancelled |
| Close ticket | POST `/my/support/ticket/<id>/close` | "Allow Portal Close" enabled in Settings AND ticket is open |
| Reopen ticket | POST `/my/support/ticket/<id>/reopen` | "Allow Portal Reopen" enabled in Settings AND ticket is resolved/closed |

### 9.8 What Customers Cannot See

- Internal notes (messages with internal subtype)
- Agent-only fields (escalation level, SLA details, internal timestamps)
- Other customers' tickets (record rules enforce partner-based isolation)
- Configuration menus and backend views

---

## 10. Configuration Reference

### 10.1 Settings (`Configuration > Settings`)

| Setting | Default | Description |
|---------|---------|-------------|
| Allow Portal Close | Off | Let customers close their own tickets from the portal |
| Allow Portal Reopen | Off | Let customers reopen closed/resolved tickets from the portal |
| Auto-Close Resolved Tickets | 0 (disabled) | Days after which resolved tickets are automatically closed |
| Default Team | None | Fallback team for tickets without a team assignment |
| Knowledge Base Suggestions | Off | Show KB article suggestions when customers type a subject |
| Customer Satisfaction (CSAT) | Off | Enable CSAT surveys after ticket resolution |

### 10.2 Business Hours (`Configuration > Business Hours`)

Default schedule: **Monday–Friday, 9:00 AM – 5:00 PM (UTC)**

- Define working days and hour ranges
- Add holidays (date ranges) that override working hours
- Link to SLA policies to compute deadlines using business hours instead of 24/7

### 10.3 Dynamic Fieldsets (`Configuration > Dynamic Fieldsets`)

Attach extra fields to specific ticket types:

1. Create a Fieldset with a name
2. Add Dynamic Fields to it (text, selection, boolean, etc.)
3. Link the Fieldset to a Ticket Type
4. When customers select that ticket type on the portal, the extra fields appear automatically

### 10.4 Security Groups

| Group | Implied By | Permissions |
|-------|-----------|-------------|
| Agent | — | Read/write own tickets, read teams/categories/tags |
| Team Lead | Agent | All agent perms + SLA management |
| Administrator | Team Lead | Full access to all configuration and data |

Record rules ensure:
- Agents see tickets assigned to them or their team
- Portal users see only their own tickets
- Public users have no ticket access

---

## 11. Default Seed Data

### Categories
| Name | Portal Visible |
|------|---------------|
| General Inquiry | Yes |
| Technical Issue | Yes |
| Billing & Payments | Yes |
| Feature Request | Yes |
| Bug Report | Yes |

### Ticket Types
| Name | Portal Visible |
|------|---------------|
| Question | Yes |
| Incident | Yes |
| Service Request | Yes |
| Feedback | Yes |

### Close Reasons
| Name | Type |
|------|------|
| Solved | Close |
| Workaround Provided | Close |
| Resolved by Third Party | Close |
| Customer Not Responding | Close |
| Duplicate | Cancel |
| Invalid / Not a Real Issue | Cancel |
| Spam | Cancel |

### Tags
Urgent, VIP Customer, Regression, Needs Documentation

### Canned Responses
| Shortcut | Name |
|----------|------|
| `/greet` | Greeting |
| `/moreinfo` | Request More Information |
| `/close` | Closing Message |

---

## 12. URL Reference

### Backend (Agents/Admins)

All backend URLs follow standard Odoo patterns via the **Helpdesk** top-level menu.

### Portal (Customers)

| URL | Auth | Description |
|-----|------|-------------|
| `/my` | Login required | Odoo portal home (shows "Support Tickets" card) |
| `/my/support` | Login required | Support dashboard with stats and recent tickets |
| `/my/support/tickets` | Login required | Paginated ticket list with filter/search/sort |
| `/my/support/ticket/new` | Login required | Ticket creation form |
| `/my/support/ticket/<id>` | Login required | Ticket detail with conversation thread |
| `/my/support/kb` | Public | Knowledge Base home — categories and search |
| `/my/support/kb/category/<id>` | Public | KB category with article list |
| `/my/support/kb/<slug>` | Public | KB article detail with voting |

---

## Quick Start Checklist

After installing all modules:

1. **Create a Team** — Configuration > Teams > New (add members, set auto-assign mode)
2. **Review Categories** — Configuration > Categories (5 defaults provided)
3. **Review Ticket Types** — Configuration > Ticket Types (4 defaults provided)
4. **Set Up SLA** — SLA Policies > New (define response/resolution targets)
5. **Configure Settings** — Configuration > Settings (enable portal close/reopen, set auto-close days)
6. **Invite Customers** — Settings > Users > Invite Portal Users
7. **Test the Portal** — Log in as a portal user, go to `/my/support`, create a test ticket
8. **Add KB Articles** — Knowledge Base > Articles > New (write helpful content)
9. **Create Macros** — Configuration > Macros (set up one-click agent actions)
10. **Set Up Triggers** — Configuration > Triggers (automate responses to events)
