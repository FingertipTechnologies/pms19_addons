{
    'name': 'Employee Competency Management',
    # 19.0.1.0.0 first release. Competency master and categories, job-position
    # competency mapping with a 100% weightage rule, review cycles, the
    # self/manager assessment workflow with automatic weighted scoring, gap
    # analysis, development plans, the employee competency profile, and the
    # pivot/graph reports over all of it (reports removed in 19.0.1.4.0).
    # 19.0.1.1.0 fixes three things an HR manager and a reviewed employee
    # both ran into.
    #   The Development Plans tab on an assessment listed plans by their
    # assessment link, and a plan raised from the Development Plans menu
    # carries none — the field is optional with no default — so the tab was
    # empty however many plans the employee had. It now lists every plan on
    # that employee's record, with the review that raised it as a column. The
    # tab's own "add a line" is gone with it: Employee is required and was
    # hidden with no default there, so a line added inline could never save.
    # A button raises one properly instead.
    #   The target job and the two summaries are the reviewing manager's, which
    # is what the field help always said and nothing enforced — an employee
    # could set where they were headed and rewrite the strengths and
    # development areas recorded about them during their own self assessment.
    # Read-only for them now, and guarded server-side in _check_manager_fields,
    # since `readonly` in a view stops a field being drawn, not written.
    # 19.0.1.2.0 takes the self-service section off the HR manager's menu bar.
    # My Assessments and My Development Plans were empty for them — an HR login
    # is hardly ever the one being assessed — and they could not simply be
    # relabelled or hidden, because a menu shown to the Employee group is shown
    # to everything that IMPLIES it, and HR implied Employee through
    # Department Manager. So it does not any more: HR Competency Manager is a
    # back-office role over the framework, not a bigger version of being
    # reviewed. Department Manager still implies Employee, because a manager IS
    # assessed as well as assessing.
    #   HR therefore stops inheriting the reviewing rights too, and has to be
    # named wherever they were assumed: `groups="...manager,...hr_manager"` on
    # the menus, the workflow buttons and the manager-only fields, and
    # competency_utils.is_competency_manager in place of the four has_group
    # checks. Every access line and record rule HR needs was already granted to
    # it in its own right, so none of those changed. Odoo 19 stores only the
    # groups a user is actually given and derives the rest, so an admin set to
    # HR Competency Manager loses the Employee group on upgrade with nothing to
    # migrate. The three roles also gain a sequence, so Settings lists them
    # Employee, Department Manager, HR rather than alphabetically.
    #   The 19.0.1.1.0 widening of those two menus is reverted with it: they
    # answer for their own records again, which is what they say they do.
    # 19.0.1.3.0 lines the module up with the Employee Competency Data Model
    # developer specification (the Excel workbook), both ways.
    #   Added from the specification: the 1-5 rating level master with its
    # progress and definitions; structured 360 feedback per competency with a
    # reviewer type and a submit lock, averaged into the line's Peer / 360
    # Rating (BR-014) and requested from the assessment; the Leadership
    # Competency flag on the job matrix; the review cycle states the
    # specification names, Draft -> Open -> Closed, with HR able to reopen;
    # Competency Code required; and the sample Salesforce Developer matrix
    # with its four functional competencies.
    #   Removed, being in the module but not in the specification: the
    # dashboard counters and UI helpers - category and competency colour, the
    # competency / job / line / gap / critical gap / strength / plan counts,
    # the cycle's assessment counts and average score, the employee's
    # assessment, plan and gap counts, the rating label helpers, and the
    # development plan's Training Required tick (the Action Type says it).
    #   Labels follow the specification: Target Level on the job matrix,
    # Expected / Previous Level on the assessment line, Owner, Due Date,
    # Description and Not Started on the development action.
    #   Migration: cycles in Assessment Running become Open and Completed
    # become Closed; the noupdate assessment mail template stops reading the
    # removed line_count.
    # 19.0.1.4.0 closes the gaps found in the review against the Employee
    # Competency Data Model developer specification (the Excel workbook).
    #   Approval flow: Employee Review -> Manager Review -> HR Approval ->
    # Completed. Each step is a button that checks who presses it (the
    # employee submits their own self assessment, a manager never reviews
    # their own, only HR approves) and the status cannot be written directly.
    # HR approval certifies the final ratings (Certified By / On) and writes
    # them onto the employee profile. "Start Manager Review", which demanded
    # manager ratings before the manager could give any, becomes Skip Self
    # Assessment.
    #   Self assessment lock: self ratings are the employee's own and lock on
    # submit; manager ratings lock on manager submit (HR only during
    # approval); nothing moves after completion.
    #   Peer feedback: reviewer selection proposes peers / the department
    # manager and refuses the employee, the reviewing manager and people with
    # no login. A peer can now actually submit (it failed reading the
    # assessment).
    #   Development actions are raised automatically for every gap when the
    # manager submits; BR-019 warns in the chatter (phase 1).
    #   History: the profile keeps the previous level and the change,
    # rebuilt from completed reviews on completion, reset and cancel.
    # Employee readiness is measured against the current target job.
    #   Appraisal goal: a custom model in place of the Enterprise
    # hr.appraisal.goal, linked from the development action (goal_id).
    #   Specification field names (competency_code, skill_id, skill_type_id,
    # appraisal_id, expected_level_id, previous_level_id, target_level_id,
    # minimum_level_id, gap_score, owner_id, due_date, description, ...) are
    # available, the level fields as links to the rating level master.
    #   Removed, being in neither the specification nor the review: the
    # Reporting menu with its Employee Competency, Department Skill Matrix and
    # Leadership Pipeline reports and every pivot / graph view; Regenerate
    # Lines; and the Gap Status bands (No Gap / Improvement Required /
    # Critical Gap). The specification's chain is Expected Level -> Final
    # Rating -> Gap Score -> Development Required, which the competency lines
    # now show in that order. The 360 feedback request picks reviewers from
    # hr.employee.public, so a department manager without HR rights can send
    # it.
    # 19.0.1.5.0:
    #   BR-018 - a completed review writes its final approved levels onto the
    # employee's Skills tab (hr.employee.skill). Each category becomes a skill
    # type carrying the 1-5 levels and each competency a skill in it, created
    # on first use. An existing skill is updated through hr_skills' own
    # handling (the old level archived as history, one current line), never
    # duplicated. Driven by the rebuilt profile, so only completed reviews
    # count, and a cancel or reset re-syncs. Depends on hr_skills.
    #   Previous Level was copied once when the lines were generated, and a
    # cycle is usually opened while the previous review is still in progress
    # - so it read 0, and Improvement with it, and never caught up. It is
    # computed now, and completing, cancelling or resetting a review refreshes
    # the baseline of the employee's open reviews.
    #   Migration: Previous Level recomputed everywhere; approved results
    # already in the database written to the employees' skills.
    # 19.0.1.6.0:
    #   Every competency email goes out from a fixed company mailbox, never
    # from the user whose click triggered it (no template set a sender, so
    # each one used the HR user's or the manager's own address). From
    # hr@fingertipplus.com: cycle opened / assessment assigned, self
    # assessment reminder, assessment completed. From
    # support@fingertipplus.com: self assessment submitted, manager review
    # completed / HR approval pending (one mail), 360 feedback request,
    # reminder and "submitted", development action created, reminder and
    # completed. Both addresses can be changed through the system parameters
    # ft_employee_competency.hr_email and .support_email. The 360 request is a
    # proper email per reviewer now instead of a notification sent as the
    # manager. Added: HR approval pending, assessment completed, 360
    # reminder (daily cron, after 3 days) and submitted, development action
    # created and completed; the development reminder also fires 3 days
    # before the due date and reaches the employee and manager as well as
    # the owner.
    #   UI: Open Full Board on the Competencies tab opens the scorecard full
    # screen; the Summary tab's two text boxes span their column.
    # 19.0.1.7.0 removes 360 feedback entirely: the employee's "360 Feedback"
    # menu and the managers' "360 Feedback" menu, the feedback model, the
    # Request 360 Feedback wizard and button, the Peer / 360 Rating column,
    # the 360 tab on the assessment, its three mail templates, the reminder
    # cron and its access rights and record rules.
    'version': '19.0.1.7.1',
    'category': 'Human Resources',
    'summary': 'Competency framework, role mapping, assessments, gaps and development plans',
    'description': """
Employee Competency Management
==============================
A competency framework for the Employees app:

 * **Rating levels** — the common 1-5 scale (Needs Improvement, Developing,
   Competent, Strong, Expert / Role Model) with its progress and definitions.
 * **Competency master** grouped by category (Leadership, Communication,
   Business Knowledge, Functional, Technical, Behaviour & Attitude, ...), each
   competency carrying a code, evaluation guideline, default weightage and the
   rating below which development is required.
 * **Job competency matrix** — the competencies each job position requires,
   with a target level, a minimum level, a weightage, a mandatory flag and a
   leadership flag.
   The weightages of a job's assessed competencies must total 100%.
 * **Review cycles** (quarterly / half-yearly / annual) with self- and
   manager-review deadlines, driving Draft -> Open -> Closed.
 * **Assessments** generated from the job matrix. Every line SNAPSHOTS the
   competency, category, scope, weightage and required level, so changing the
   job matrix later never rewrites history.
 * **Scoring** on the 1-5 scale: a line contributes (Final Rating / 5) x
   Weightage points, and the assessment totals them into an overall score out
   of 100 and out of 5, split by core / functional / leadership.
 * **Gap analysis** — Gap Score is Final Rating minus Expected Level; a
   negative gap, or a rating under the development threshold, sets
   Development Required.
 * **Development plans** raised against a gap, with an owner, a target date and
   progress tracking.
 * **Employee competency profile** — the latest approved level per competency,
   written back when an assessment completes, plus quarter-on-quarter
   improvement and readiness for a target role.
 * **Approval workflow** — self assessment, manager review, HR approval and
   certification.
 * **Goals** linked to development actions.
 * **Competency history** — the profile keeps the previous level and the
   change against it.

Built on ``hr`` alone. It does not require the Enterprise ``hr_appraisal``
module: the assessment plays the part of ``hr.appraisal`` and the goal that
of ``hr.appraisal.goal``, both defined here. Approved levels
are written to the employee skills of the Community ``hr_skills`` module.
""",
    'author': 'Fingertip',
    'website': '',
    'depends': [
        'hr',
        'hr_skills',
        'mail',
        'web',
    ],
    'data': [
        'security/competency_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/mail_template_data.xml',
        'data/ir_cron_data.xml',
        'views/competency_level_views.xml',
        'views/competency_category_views.xml',
        'views/competency_views.xml',
        'views/hr_job_views.xml',
        'views/competency_cycle_views.xml',
        'views/competency_assessment_views.xml',
        'views/competency_profile_views.xml',
        'views/development_plan_views.xml',
        'views/hr_employee_views.xml',
        'views/appraisal_goal_views.xml',
        'views/competency_menus.xml',
        'data/competency_master_data.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
