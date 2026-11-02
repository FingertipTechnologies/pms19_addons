# Implementation Payment Milestones (`ft_implementation_milestone`)

Payment milestone plan of an **Implementation** project (PMS requirements
51–56): the milestones every project starts with, the 100 % rule, the plan
required to leave KICKOFF, and the locked plan with its change-request
exception flow.

Everything is added by inheritance on top of `project_custom_milestone`
(the `project.custom.milestone` model behind the project form's *Milestones*
tab), `qa_testapp` (the tab itself), `ft_pms_planning_workflow` (stage
gates), `ft_project_stage_dates` (KICKOFF stage) and `project_date_extension`
(the approver group and the due-date guard). AMC and General projects are not
affected.

## Menus

Under **Project ▸ Milestones** (the root menu of `project_custom_milestone`):

| Menu | Who | What |
|---|---|---|
| Project Milestones | everyone | existing list; a `%` column is added |
| Milestone Change Requests | project users | raise / follow requests; approvers decide |
| Milestone Templates | project managers, administrators | the milestones every new Implementation project starts with |

On the project form: the plan total in the *Milestones* tab, and a
**Milestone Changes** stat button (count).
On a milestone form: a **Request a Change** link (when locked) and a
**Change Requests** stat button.

## Milestone Templates

Since 19.0.1.2.0 the templates are **flat**: *Milestone Templates* is the
list of milestones itself (Advance, BRD Approval, After Sandbox Review,
Before UAT, After UAT, Before First User Onboarding, Final Project Handover),
edited in place and reordered by drag and drop. There is no parent
"Standard Implementation" plan and **no percentage on a template**: the
percentages are agreed per project. A template carries a name (unique), an
order, an informational *Delivery Stage* and a description that is copied
onto the project milestone. Archive a template to stop adding it to new
projects.

## Flow

1. **Project creation** – an Implementation project created without a
   milestone of its own (the creation form, a conversion of a General / AMC
   project to Implementation) receives **every active template as a
   milestone with 0 %**, no amount and no due date, so the *Milestones* tab
   lists the agreed names from the start. A project created *with* its own
   milestones (import, RPC, a plan typed in the creation form) is left as
   entered; the context key `ft_skip_template_milestones` skips the templates
   entirely.
2. **KICKOFF** – the PM enters the agreed percentage (and amount / date, if
   known) of each milestone in the *Milestones* tab; extra milestones can be
   added by hand there.
3. **KICKOFF → DISC** (and every later forward move) – the move is refused
   unless the milestone percentages add up to **100 %**. The message is the
   usual stage-gate one, with the item:

   > Payment Milestones: the milestone percentages must add up to 100%
   > (currently 0%). Adjust them in the Milestones tab.

   The form's *Missing for Next Stage* checklist shows it live, and a plan
   completed in the same save as the move counts. Project *creation* is not
   gated on 100 % (the templates satisfy the "at least one milestone" rule;
   the percentages are entered during KICKOFF).
4. **After KICKOFF** – the plan is **locked**: name, percentage, amount, due
   date (and project) of a milestone cannot be changed, no milestone added
   or removed, by anyone but a *Date Extension Approver (Admin)*. Status,
   paid amount, hours, description and attachments stay editable. The
   due-date rule of `project_date_extension` still applies on top.
5. **Exception** – a **Milestone Change Request** (`MCR/<year>/0001`):
   *update* one milestone, *add* one, or *remove* one (never an invoiced or
   paid one), with a reason. Draft → *Submit for Approval* → an approver
   *Approves* (the change is applied at once, under the approval context)
   or *Rejects* with a reason. Approval is refused when the plan would not
   total 100 % afterwards — the error states the resulting total. Decided
   requests cannot be deleted; a rejected one can be reset to draft and
   resubmitted.

## Customer e-mail on milestone completion

When a payment milestone of an Implementation project is marked
**Completed** (inline list, milestone form, import, RPC), the e-mail
template *Implementation: Milestone Completed* is queued to the project's
customer (`partner_id` e-mail) with the milestone name, share, amount, due
date and Project Manager, and the project's chatter records it. The switch
**E-mail customer when a milestone is completed** on the project's
*Milestones* tab (default on) turns it off per project. A customer without
e-mail address gets a chatter note instead; a failure to prepare the mail is
logged and never blocks the status change. AMC monthly milestones are not
concerned (they have the monthly timesheet e-mail of
`ft_amc_payment_milestone`).

## Upgrade from 19.0.1.1.0

The pre-migration flattens the data: every line of the old plan(s) becomes
its own template (one per name, plan order kept, percentages dropped), the
parent records and the line table are removed, and the seven standard
milestones keep their records (the new xmlids are attached by name, so the
`noupdate` data file neither duplicates nor overwrites them). Existing
projects are untouched: add the milestones by hand in the *Milestones* tab
of an early-stage project that should get the set.

## Technical notes

* `ft.milestone.template`: `name` (unique), `sequence`, `active`,
  `stage_key`, `description`; `_ft_milestone_vals(project=None)` gives the
  `project.custom.milestone` values (0 %, no amount / date).
* `project.project`: `_ft_template_milestone_commands(existing_names)` (the
  One2many create commands of the templates not yet on the project, by
  name); `create` injects them into an Implementation create without
  `custom_milestone_ids`; `write` does the same when `ft_project_type`
  becomes `implementation` on a project without payment milestones (the
  lock snapshot marks the plan unlocked for that write).
  `ft_milestone_percentage_total`, `ft_milestone_plan_ok`,
  `ft_milestone_plan_locked`, `ft_milestone_plan_editable`,
  `ft_milestone_change_request_ids/_count`; gate via
  `_pwf_transition_missing` (super + the 100 % item, reading the x2many
  commands of the write in progress); `_compute_pwf_next_stage_missing`
  re-declared with `custom_milestone_ids.percentage` as dependency.
* `project.custom.milestone`: `ft_milestone_plan_locked`, percentage 0–100
  constraint, lock in `create` / `write` / `unlink`. Bypass: superuser, the
  approver group, or the context key `ft_milestone_change_approval`.
* Lock evaluation during a project write that changes both the stage and
  the milestone lines uses a snapshot of the pre-write stage (context key
  `ft_milestone_lock_snapshot`), so a PM may complete the plan and move
  KICKOFF → DISC in one save.
* No contract value field exists on the project in this PMS.
  `project.project._ft_milestone_contract_value()` (the linked Sales
  Order's untaxed total, else 0) is kept as the one place to read it from
  should milestone amounts ever be derived from the percentages again;
  nothing calls it since the templates stopped carrying percentages.
* Tests: `tests/test_implementation_milestone.py` (`post_install`).
