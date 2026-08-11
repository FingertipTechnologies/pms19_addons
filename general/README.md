# General — Odoo 18 Module

Single module providing three internal-operations sub-systems:

- **Asset Management** — categories, asset master, employee assignment, maintenance
- **Expense Management** — categories, expense claims with bill lines, advances
- **Recruitment** — job positions, candidates, interviews, offers, onboarding

Each sub-system has its own **top-level menu** in the Odoo navbar:

- 📦 Asset Management
- 💰 Expense Management
- 👥 Recruitment

---

## Installation

1. Copy the entire `general` folder into your Odoo addons path
   (e.g. `local_addons/general/`).
2. Restart the Odoo server.
3. Go to **Apps → Update Apps List**.
4. Search for **General** and click **Install**.

The module depends only on `base`, `mail`, and `hr` — no other third-party
modules required.

---

## Models created (13 total)

### Asset Management
| Model | Purpose |
|---|---|
| `asset.category` | Asset categories (Laptop, Phone, Monitor…) |
| `company.asset` | Asset master record with auto-generated codes |
| `asset.assignment` | Handover and return history per employee |
| `asset.maintenance` | Repair and service tracking |

### Expense Management
| Model | Purpose |
|---|---|
| `expense.category` | Categories with bill / approval / limit rules |
| `employee.expense.claim` | Claim header with workflow Draft → Submitted → Approved → Paid |
| `employee.expense.line` | Individual expense lines with bill attachments |
| `employee.advance` | Cash advances with automatic adjustment tracking |

### Recruitment
| Model | Purpose |
|---|---|
| `recruitment.job.position` | Open positions with hiring requirements |
| `recruitment.candidate` | Candidate database with pipeline stages |
| `recruitment.interview` | Interview rounds with scheduling and feedback |
| `recruitment.offer` | Offer management with workflow |
| `employee.onboarding` | Joining checklist; auto-creates `hr.employee` on completion |

---

## Security groups

Six groups in three pairs (User / Manager):

- Asset User / Asset Manager
- Expense User / Expense Manager
- Recruitment User / Recruitment Manager

Regular Expense Users only see their own claims; Expense Managers see all.
Multi-company rules are enforced on key models.

---

## Sequences

Auto-generated codes:

- `LAP-0001` (asset code, prefix taken from the category)
- `EXP-0001` (expense claim number)
- `ADV-0001` (advance number)

---

## Workflows included

- **Expense Claim**: Draft → Submitted → Approved → Paid (with Reject and Reset to Draft)
- **Asset Maintenance**: Open → In Progress → Completed (also auto-flips the asset's status to Under Repair)
- **Asset Assignment**: enforces "one active assignment per asset"; auto-updates asset status on assign/return
- **Recruitment Offer**: Draft → Sent → Accepted / Rejected / Withdrawn
- **Onboarding**: creates `hr.employee` when the checklist is complete

---

## Phase notes (per the Excel blueprint)

This module includes both Phase 1 (MVP) and Phase 2 models:

- Phase 1: categories, masters, assignments, claims with lines, candidates, interviews, job positions
- Phase 2: maintenance, advances, offers, onboarding

Everything is installable in one go — there is no separate Phase 1 install path.

---

## After install

Look for these three new icons in the Odoo navbar:

1. **Asset Management** → Assets / Assignments / Maintenance / Configuration → Categories
2. **Expense Management** → Expense Claims / Advances / Configuration → Categories
3. **Recruitment** → Job Positions / Candidates / Interviews / Offers / Onboarding

Create at least one **Asset Category** before creating an Asset (the code prefix
is taken from the category — e.g. category prefix `LAP` → asset code `LAP-0001`).

Create at least one **Expense Category** before creating an Expense Claim line.

Create at least one **Job Position** before creating a Candidate.

---

# Menus & Reports

Each module now has a **Reports** sub-menu with pivot/graph/list analysis views.

## Asset Management → Reports
- **Asset Register** — all assets (list / pivot / graph) by category and status, with purchase cost measure
- **Employee Asset Report** — assignments pivot by employee and month
- **Repair Cost Report** — maintenance pivot/graph by asset, vendor, status with repair cost
- **Warranty Expiry Report** — assets with a warranty end date; expired rows shown in red

## Expense Management → Reports
- **Pending Approval Report** — claims in Submitted status awaiting approval
- **Project-wise Expense** — expense lines pivot/graph by project / client / category
- **Advance Settlement Report** — advances pivot by employee and status with balance
- **Monthly Expense Summary** — claims pivot/graph by month and employee

## Recruitment → Reports
- **Open Position Report** — open positions by department (pivot/graph), with openings count
- **Candidate Pipeline** — candidates kanban/pivot/graph by stage, position, source
- **Interview Schedule** — interviews calendar/pivot by date and interviewer
- **Offer Status Report** — offers pivot by position and status with CTC measure
- **Joining Checklist** — onboarding readiness by joining date and status

Configuration menus: **Asset → Categories**, **Expense → Categories**,
**Recruitment → Skills** (shared skill tags).

---

# Dropdown / Selection Values

All selection fields follow the agreed master list:

| Model | Field | Values |
|---|---|---|
| company.asset | Current Status | Available, Assigned, Under Repair, Lost, Sold, Scrapped |
| company.asset | Asset Condition | New, Good, Average, Damaged |
| asset.assignment | Return Condition | Good, Damaged, Missing Parts |
| asset.maintenance | Status | Open, In Progress, Completed, Cancelled |
| employee.expense.claim | Approval Status | Draft, Submitted, Approved, Rejected, Paid |
| employee.expense.claim | Payment Status | Unpaid, Paid |
| employee.expense.line | Payment Mode | Cash, UPI, Card, Company Card, Bank Transfer |
| employee.advance | Status | Open, Partially Adjusted, Closed |
| recruitment.job.position | Employment Type | Full-time, Internship, Contract, Consultant |
| recruitment.job.position | Status | Open, On Hold, Closed |
| recruitment.candidate | Source | LinkedIn, Naukri, Referral, Website, Walk-in, Consultant, Other |
| recruitment.candidate | Candidate Status | New, Screened, Interview, Selected, Rejected, Offered, Joined |
| recruitment.interview | Interview Round | HR, Technical 1, Technical 2, Management, Client |
| recruitment.interview | Interview Mode | Online, Offline, Phone |
| recruitment.interview | Status | Scheduled, Completed, No Show, Cancelled |
| recruitment.interview | Result | Selected, Rejected, Hold |
| recruitment.offer | Offer Status | Draft, Sent, Accepted, Rejected, Withdrawn |
| employee.onboarding | Status | Pending, In Progress, Completed |

---

# Implementation Notes

| Area | Recommendation | Status in this module |
|---|---|---|
| Access Rights | Groups like User / Manager per module | ✅ 6 groups (Asset, Expense, Recruitment × User/Manager) |
| Sequences | Auto codes for Asset, Claim, Advance | ✅ LAP-/EXP-/ADV- sequences |
| Chatter | mail.thread + mail.activity.mixin on main models | ✅ enabled on all main models |
| Attachments | ir.attachment for invoices, resumes, offer letters, handover forms | ✅ binary attachment fields throughout |
| Approvals | Status fields drive the workflow | ✅ status selection fields (manual transitions) |
| Computed Fields | Total, Adjusted, Balance, Current Employee | ✅ all computed |
| Dashboards | list, kanban, pivot, graph before custom dashboards | ✅ pivot + graph report views added |
| Phase 1 Scope | Asset master, assignment, expense claims, candidates, interviews, job positions | ✅ included |
| Phase 2 Scope | Maintenance, advances, offers, onboarding, alerts | ✅ included (depreciation left for future) |

---

# Dashboards (Odoo 18 Community)

Built with the classic **board.board** dashboard (no JavaScript, Community-friendly).
Each module gets a **Dashboard** menu at the top combining its key charts.
Requires the standard **board** module (added to dependencies).

## Asset Management → Dashboard
- Assets by Category (graph)
- Repair Cost by Month (graph)
- Warranty Expiry (list)

## Expense Management → Dashboard
- Expense by Month (graph)
- Project / Client Cost (graph)
- Pending Approval (list)
- Advance Settlement (list)

## Recruitment → Dashboard
- Candidate Pipeline (graph)
- Openings by Department (graph)
- Interview Schedule (list)
- Offer Status (list)

Note: board.board is the dashboard available in Community Edition. The drag-and-drop
spreadsheet dashboards are Enterprise-only. Each block here is interactive — click
through to the underlying records, switch chart types, and re-group as needed.
