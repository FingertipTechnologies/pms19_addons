# QA TestApp – Test & Bug Tracker

## Overview
A comprehensive Quality Assurance suite for Odoo 18 covering:
- Test Plans (scope, objectives, approach, schedule, approval)
- Test Scenarios (tracking, comments, project)
- Test Cases (stepwise execution, preconditions, severity, result)
- Bug Tickets (ID, reporter, steps, severity, device, evidence, full lifecycle)

## Features

### Test Plan
- Project, ORG, Introduction, Objectives, Scope, Approach, Env, Dates
- Approval, Roles, Defect Mgmt, Constraints, Assumptions

### Test Scenario
- Scenario ID, S No, Module, Status, Comments (PM), Project

### Test Case
- Title, ID, Objective, Preconditions, Steps, Data, Result, Severity
- Execution tracking, Type

### Ticket/Bug
- Auto Bug ID, Title/Summary, Description, Steps to Reproduce, Expected/Actual Result
- Severity, Priority, Status, Reproducibility, Device, Environment, Project/ORG, Reporter & Date, Evidence (notes & attachments), Related test case
- Uses Odoo Chatter for notes & attachments

## Installation

1. Place `qa_testapp/` in your Odoo 18 `addons/` directory
2. Update app list
3. Install "QA TestApp – Test & Bug Tracker"

## Security

By default, all authenticated users have full CRUD rights on all four models (Test Plan, Scenario, Case, Bug Ticket).

---

For more documentation, feature requests or support, contact **Fingertip**.