# FT AMC Monthly Timesheet

Every month, each AMC customer automatically receives the timesheet of the
work that was **completed and approved** on their project in the previous
month, as a PDF and an Excel file.

## How it works

1. An AMC project (Project Type = AMC) has tasks; the team logs timesheets on them.
2. When a task reaches a completed (final) stage, the Project Manager / Team
   Lead approves it (task form, or the **Approve** button on the task list).
3. On or after the **5th of each month** a daily scheduled job builds, for every
   active AMC project, the report of the **previous calendar month**:
   - timesheet entries **dated** 1st to last day of that month (billable and non-billable);
   - only of tasks that are completed and approved when the report runs.
   Approve tasks before the 5th: entries of a task approved after its month's
   report was sent are not emailed later.
4. A PDF and an Excel file are generated and e-mailed to the customer.
   If there are no such entries, nothing is sent (report status *No Data*); the
   daily job re-checks it for the rest of the month, so tasks approved after the
   5th are still sent.

If the job could not run on the 5th, the next daily run in that month sends the
report. Failed reports are retried automatically the next day. Each project gets
at most one report per month.

## Configuration

**Project** (form of an AMC project):
- *Customer* with a valid e-mail - required, the report goes to this address.
- *Start Date* / *End Date* - the AMC contract period; the month must fall
  within it. Projects without a start date are skipped.
- *POC Email* (optional) - also receives the report.
- Tab **AMC Monthly Timesheet**: *Send monthly AMC timesheet* (on by default)
  and *Additional report recipients*. The Project Manager is put in CC.

**Settings > Project > AMC Monthly Timesheet**:
- *Report Sender* - sender / reply-to address
  (default `Support Fingertip <support@fingertipplus.com>`).
- *First Reporting Month* - first day of the first month to report.
  Example: `2026-10-01` -> the first e-mail is sent on 5 Nov 2026 (for October).
  Earlier months are never sent automatically.

Outgoing mail must be configured (Settings > Technical > Outgoing Mail Servers).

## PDF generation (ReportLab)

The PDF is drawn in pure Python with **ReportLab** - wkhtmltopdf is not used
and not needed (there is no QWeb PDF report / *Print* menu entry for it).
ReportLab is part of Odoo 19's own `requirements.txt` (`reportlab==4.1.0` for
Python >= 3.12), so a standard Odoo installation already has it. Check with the
Python interpreter that runs Odoo:

    python3 -c "import reportlab; print(reportlab.Version)"

If it is missing, install it in Odoo's virtualenv (no sudo needed):

    /path/to/odoo-venv/bin/pip install reportlab

Report content (PDF and Excel are identical, the Excel has a single sheet):
company header, the info block (Customer, Project, Reporting month, Period,
Total hours) and a **Tasks** table with one row per task - Date (the task's
approval date), Task, Hours - sorted by task name. A task's hours are the sum
of its timesheet entries dated in the reporting month (each entry is counted
once); the last row is the report's total hours. Individual timesheet entries
are not listed (they are kept on the report record for its totals).

Hours are shown as **HH:MM** (e.g. 7.83 h -> `07:50`), rounded to the nearest
minute and balanced so that the task rows add up exactly to the shown total.
In the Excel file they are real durations (format `[h]:mm`), so they can be
summed. The PDF footer shows the company name, e-mail, website and the fixed


Dates in the PDF and the Excel file are shown in the company timezone
(company contact's timezone, default Asia/Kolkata).

If the PDF or the Excel file cannot be generated, the report is set to
**Failed** with the reason (e.g. *PDF generation failed: ...*), **no e-mail is
sent**, and the file that could be produced stays available for download. The
error is logged with the report id, project and period. Failed reports are
retried by the next daily run, or use **Generate / Refresh** / **Send Now**
once the problem is fixed.

## Approving older tasks (one-time)

Tasks completed before go-live are not approved yet. Open
**Project > AMC Reports > Tasks Awaiting Approval** (or *All Tasks* with the
*To Approve* filter), select the tasks and click **Approve**. They are counted
in the month in which they are approved.

## Manual actions

- Project tab: **Generate Month (Preview)** - pick a month (the previous month
  is proposed when the contract covers it, otherwise the current one) and build
  its report without sending it. A month outside the contract dates is refused.
- **Project > AMC Reports > AMC Monthly Timesheets** - all reports. On a report:
  - **Generate / Refresh** - rebuild lines, PDF and Excel (no e-mail);
  - **Send Now** - e-mail it immediately (completed months only);
  - **Download PDF / Download Excel**;
  - **Refresh Email Status** and **Reset to Draft** (failed / no data).

Access: *AMC Reporting Manager* group, Project Administrators and Settings administrators.
