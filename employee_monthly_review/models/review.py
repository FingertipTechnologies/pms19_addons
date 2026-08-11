# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError

RATING = [
    ('1', '1 - Very Poor'),
    ('2', '2 - Needs Improvement'),
    ('3', '3 - Meets Expectations'),
    ('4', '4 - Exceeds Expectations'),
    ('5', '5 - Outstanding'),
]

ROLE = [
    ('sales', 'Sales'),
    ('marketing', 'Marketing'),
    ('developer', 'Developer'),
    ('team_lead', 'Team Lead'),
    ('project_manager', 'Project Manager'),
    ('tester', 'Tester / QA'),
    ('hr', 'HR'),
]

class Review(models.Model):
    _name = "review"
    _description = "Monthly Employee Review"
    _order = "review_month desc, employee_id"

    name = fields.Char(compute="_compute_name", store=True)
    employee_id = fields.Many2one("hr.employee", required=True, index=True)
    reviewer_id = fields.Many2one("res.users", default=lambda self: self.env.user, required=True)
    review_month = fields.Date(required=True, index=True, help="Use month start date like 2026-02-01")
    role = fields.Selection(ROLE, required=True)

    # -------------------------
    # COMMON (6) - rating + comment
    # -------------------------
    communication_clarity_rating = fields.Selection(RATING)
    communication_clarity_comment = fields.Text(required=True)

    accountability_ownership_rating = fields.Selection(RATING)
    accountability_ownership_comment = fields.Text(required=True)

    deadline_discipline_rating = fields.Selection(RATING)
    deadline_discipline_comment = fields.Text(required=True)

    work_quality_rating = fields.Selection(RATING)
    work_quality_comment = fields.Text(required=True)

    process_adherence_rating = fields.Selection(RATING)
    process_adherence_comment = fields.Text(required=True)

    learning_improvement_rating = fields.Selection(RATING)
    learning_improvement_comment = fields.Text(required=True)

    # -------------------------
    # SALES (5)
    # -------------------------
    prospecting_pipeline_discipline_rating = fields.Selection(RATING)
    prospecting_pipeline_discipline_comment = fields.Text()

    follow_up_deal_progression_rating = fields.Selection(RATING)
    follow_up_deal_progression_comment = fields.Text()

    discovery_questioning_quality_rating = fields.Selection(RATING)
    discovery_questioning_quality_comment = fields.Text()

    objection_handling_negotiation_rating = fields.Selection(RATING)
    objection_handling_negotiation_comment = fields.Text()

    forecast_accuracy_revenue_ownership_rating = fields.Selection(RATING)
    forecast_accuracy_revenue_ownership_comment = fields.Text()

    # -------------------------
    # MARKETING (5)
    # -------------------------
    campaign_planning_execution_rating = fields.Selection(RATING)
    campaign_planning_execution_comment = fields.Text()

    lead_quality_contribution_rating = fields.Selection(RATING)
    lead_quality_contribution_comment = fields.Text()

    performance_tracking_reporting_rating = fields.Selection(RATING)
    performance_tracking_reporting_comment = fields.Text()

    tool_proficiency_ads_automation_crm_rating = fields.Selection(RATING)
    tool_proficiency_ads_automation_crm_comment = fields.Text()

    creativity_experimentation_rating = fields.Selection(RATING)
    creativity_experimentation_comment = fields.Text()

    # -------------------------
    # DEVELOPER (5)
    # -------------------------
    technical_competency_rating = fields.Selection(RATING)
    technical_competency_comment = fields.Text()

    code_quality_standards_rating = fields.Selection(RATING)
    code_quality_standards_comment = fields.Text()

    debugging_root_cause_rating = fields.Selection(RATING)
    debugging_root_cause_comment = fields.Text()

    requirement_understanding_accuracy_rating = fields.Selection(RATING)
    requirement_understanding_accuracy_comment = fields.Text()

    estimation_accuracy_reliability_rating = fields.Selection(RATING)
    estimation_accuracy_reliability_comment = fields.Text()

    # -------------------------
    # TEAM LEAD (5)
    # -------------------------
    task_planning_allocation_rating = fields.Selection(RATING)
    task_planning_allocation_comment = fields.Text()

    delivery_predictability_rating = fields.Selection(RATING)
    delivery_predictability_comment = fields.Text()

    mentoring_technical_guidance_rating = fields.Selection(RATING)
    mentoring_technical_guidance_comment = fields.Text()

    risk_identification_escalation_rating = fields.Selection(RATING)
    risk_identification_escalation_comment = fields.Text()

    stakeholder_client_communication_rating = fields.Selection(RATING)
    stakeholder_client_communication_comment = fields.Text()

    # -------------------------
    # PROJECT MANAGER (5)
    # -------------------------
    project_planning_timeline_control_rating = fields.Selection(RATING)
    project_planning_timeline_control_comment = fields.Text()

    scope_change_management_rating = fields.Selection(RATING)
    scope_change_management_comment = fields.Text()

    risk_dependency_management_rating = fields.Selection(RATING)
    risk_dependency_management_comment = fields.Text()

    stakeholder_communication_rating = fields.Selection(RATING)
    stakeholder_communication_comment = fields.Text()

    status_reporting_accuracy_rating = fields.Selection(RATING)
    status_reporting_accuracy_comment = fields.Text()

    # -------------------------
    # TESTER / QA (5)
    # -------------------------
    test_case_design_quality_rating = fields.Selection(RATING)
    test_case_design_quality_comment = fields.Text()

    bug_reporting_clarity_rating = fields.Selection(RATING)
    bug_reporting_clarity_comment = fields.Text()

    coverage_edge_case_thinking_rating = fields.Selection(RATING)
    coverage_edge_case_thinking_comment = fields.Text()

    regression_discipline_rating = fields.Selection(RATING)
    regression_discipline_comment = fields.Text()

    quality_ownership_rating = fields.Selection(RATING)
    quality_ownership_comment = fields.Text()

    # -------------------------
    # HR (5)
    # -------------------------
    hiring_pipeline_management_rating = fields.Selection(RATING)
    hiring_pipeline_management_comment = fields.Text()

    policy_compliance_documentation_rating = fields.Selection(RATING)
    policy_compliance_documentation_comment = fields.Text()

    employee_issue_handling_rating = fields.Selection(RATING)
    employee_issue_handling_comment = fields.Text()

    process_improvement_initiative_rating = fields.Selection(RATING)
    process_improvement_initiative_comment = fields.Text()

    confidentiality_professionalism_rating = fields.Selection(RATING)
    confidentiality_professionalism_comment = fields.Text()

    # -------------------------
    # After section
    # -------------------------
    strengths_top3 = fields.Text(string="Strengths")
    improvements_top3 = fields.Text(string="Improvement Areas")
    goals_next_month = fields.Text(string="Goals for Next Month")

    overall_rating = fields.Float(
        string="Overall Rating",
        compute="_compute_overall_rating",
        store=True
    )

    overall_rating_label = fields.Selection(
        RATING,
        string="Overall Rating Level",
        compute="_compute_overall_rating",
        store=True
    )

    @api.depends(
        'communication_clarity_rating',
        'accountability_ownership_rating',
        'deadline_discipline_rating',
        'work_quality_rating',
        'process_adherence_rating',
        'learning_improvement_rating',

        'prospecting_pipeline_discipline_rating',
        'follow_up_deal_progression_rating',
        'discovery_questioning_quality_rating',
        'objection_handling_negotiation_rating',
        'forecast_accuracy_revenue_ownership_rating',

        'campaign_planning_execution_rating',
        'lead_quality_contribution_rating',
        'performance_tracking_reporting_rating',
        'tool_proficiency_ads_automation_crm_rating',
        'creativity_experimentation_rating',

        'technical_competency_rating',
        'code_quality_standards_rating',
        'debugging_root_cause_rating',
        'requirement_understanding_accuracy_rating',
        'estimation_accuracy_reliability_rating',

        'task_planning_allocation_rating',
        'delivery_predictability_rating',
        'mentoring_technical_guidance_rating',
        'risk_identification_escalation_rating',
        'stakeholder_client_communication_rating',

        'project_planning_timeline_control_rating',
        'scope_change_management_rating',
        'risk_dependency_management_rating',
        'stakeholder_communication_rating',
        'status_reporting_accuracy_rating',

        'test_case_design_quality_rating',
        'bug_reporting_clarity_rating',
        'coverage_edge_case_thinking_rating',
        'regression_discipline_rating',
        'quality_ownership_rating',

        'hiring_pipeline_management_rating',
        'policy_compliance_documentation_rating',
        'employee_issue_handling_rating',
        'process_improvement_initiative_rating',
        'confidentiality_professionalism_rating'
    )
    def _compute_overall_rating(self):

        rating_fields = [
            'communication_clarity_rating',
            'accountability_ownership_rating',
            'deadline_discipline_rating',
            'work_quality_rating',
            'process_adherence_rating',
            'learning_improvement_rating',

            'prospecting_pipeline_discipline_rating',
            'follow_up_deal_progression_rating',
            'discovery_questioning_quality_rating',
            'objection_handling_negotiation_rating',
            'forecast_accuracy_revenue_ownership_rating',

            'campaign_planning_execution_rating',
            'lead_quality_contribution_rating',
            'performance_tracking_reporting_rating',
            'tool_proficiency_ads_automation_crm_rating',
            'creativity_experimentation_rating',

            'technical_competency_rating',
            'code_quality_standards_rating',
            'debugging_root_cause_rating',
            'requirement_understanding_accuracy_rating',
            'estimation_accuracy_reliability_rating',

            'task_planning_allocation_rating',
            'delivery_predictability_rating',
            'mentoring_technical_guidance_rating',
            'risk_identification_escalation_rating',
            'stakeholder_client_communication_rating',

            'project_planning_timeline_control_rating',
            'scope_change_management_rating',
            'risk_dependency_management_rating',
            'stakeholder_communication_rating',
            'status_reporting_accuracy_rating',

            'test_case_design_quality_rating',
            'bug_reporting_clarity_rating',
            'coverage_edge_case_thinking_rating',
            'regression_discipline_rating',
            'quality_ownership_rating',

            'hiring_pipeline_management_rating',
            'policy_compliance_documentation_rating',
            'employee_issue_handling_rating',
            'process_improvement_initiative_rating',
            'confidentiality_professionalism_rating'
        ]

        for rec in self:

            values = []

            for field in rating_fields:
                rating = rec[field]
                if rating:
                    values.append(int(rating))

            if values:
                avg = sum(values) / len(values)
                rec.overall_rating = round(avg, 2)

                rounded = round(avg)

                rec.overall_rating_label = str(rounded)

            else:
                rec.overall_rating = 0
                rec.overall_rating_label = False

    _uniq_review_employee_month_reviewer = models.Constraint(
        "unique(employee_id, review_month, reviewer_id)",
        "A review already exists for this employee for the same month by this reviewer.",
    )

    @api.depends("employee_id", "review_month", "reviewer_id")
    def _compute_name(self):
        for rec in self:
            if rec.employee_id and rec.review_month and rec.reviewer_id:
                m = fields.Date.to_string(rec.review_month)[:7]
                rec.name = f"{m} - {rec.employee_id.name} (by {rec.reviewer_id.name})"
            else:
                rec.name = "Monthly Review"

    def _comment_required(self, rating, comment, label):
        if rating in ("1", "2") and not (comment and comment.strip()):
            raise ValidationError(f'Comment is mandatory for "{label}" when rating is 1 or 2.')

    def _field_required(self, value, label):
        if not value or (isinstance(value, str) and not value.strip()):
            raise ValidationError(f'"{label}" is required for the selected role.')
        if '_comment' in label.lower().replace(' ', '_') and isinstance(value, str) and len(value.strip()) < 100:
            raise ValidationError(f'"{label}" must be at least 100 characters (currently {len(value.strip())}).')

    def _check_comment_min_length(self, value, label):
        if value and isinstance(value, str) and len(value.strip()) < 100:
            raise ValidationError(f'"{label}" must be at least 100 characters (currently {len(value.strip())}).')

    @api.constrains('role',
        'prospecting_pipeline_discipline_rating', 'prospecting_pipeline_discipline_comment',
        'follow_up_deal_progression_rating', 'follow_up_deal_progression_comment',
        'discovery_questioning_quality_rating', 'discovery_questioning_quality_comment',
        'objection_handling_negotiation_rating', 'objection_handling_negotiation_comment',
        'forecast_accuracy_revenue_ownership_rating', 'forecast_accuracy_revenue_ownership_comment',
        'campaign_planning_execution_rating', 'campaign_planning_execution_comment',
        'lead_quality_contribution_rating', 'lead_quality_contribution_comment',
        'performance_tracking_reporting_rating', 'performance_tracking_reporting_comment',
        'tool_proficiency_ads_automation_crm_rating', 'tool_proficiency_ads_automation_crm_comment',
        'creativity_experimentation_rating', 'creativity_experimentation_comment',
        'technical_competency_rating', 'technical_competency_comment',
        'code_quality_standards_rating', 'code_quality_standards_comment',
        'debugging_root_cause_rating', 'debugging_root_cause_comment',
        'requirement_understanding_accuracy_rating', 'requirement_understanding_accuracy_comment',
        'estimation_accuracy_reliability_rating', 'estimation_accuracy_reliability_comment',
        'task_planning_allocation_rating', 'task_planning_allocation_comment',
        'delivery_predictability_rating', 'delivery_predictability_comment',
        'mentoring_technical_guidance_rating', 'mentoring_technical_guidance_comment',
        'risk_identification_escalation_rating', 'risk_identification_escalation_comment',
        'stakeholder_client_communication_rating', 'stakeholder_client_communication_comment',
        'project_planning_timeline_control_rating', 'project_planning_timeline_control_comment',
        'scope_change_management_rating', 'scope_change_management_comment',
        'risk_dependency_management_rating', 'risk_dependency_management_comment',
        'stakeholder_communication_rating', 'stakeholder_communication_comment',
        'status_reporting_accuracy_rating', 'status_reporting_accuracy_comment',
        'test_case_design_quality_rating', 'test_case_design_quality_comment',
        'bug_reporting_clarity_rating', 'bug_reporting_clarity_comment',
        'coverage_edge_case_thinking_rating', 'coverage_edge_case_thinking_comment',
        'regression_discipline_rating', 'regression_discipline_comment',
        'quality_ownership_rating', 'quality_ownership_comment',
        'hiring_pipeline_management_rating', 'hiring_pipeline_management_comment',
        'policy_compliance_documentation_rating', 'policy_compliance_documentation_comment',
        'employee_issue_handling_rating', 'employee_issue_handling_comment',
        'process_improvement_initiative_rating', 'process_improvement_initiative_comment',
        'confidentiality_professionalism_rating', 'confidentiality_professionalism_comment',
    )
    def _check_role_fields_required(self):
        ROLE_FIELDS = {
            'sales': [
                ('prospecting_pipeline_discipline_comment', 'Prospecting Pipeline Discipline Comment'),
                ('follow_up_deal_progression_comment', 'Follow Up Deal Progression Comment'),
                ('discovery_questioning_quality_comment', 'Discovery Questioning Quality Comment'),
                ('objection_handling_negotiation_comment', 'Objection Handling Negotiation Comment'),
                ('forecast_accuracy_revenue_ownership_comment', 'Forecast Accuracy Revenue Ownership Comment'),
            ],
            'marketing': [
                ('campaign_planning_execution_comment', 'Campaign Planning Execution Comment'),
                ('lead_quality_contribution_comment', 'Lead Quality Contribution Comment'),
                ('performance_tracking_reporting_comment', 'Performance Tracking Reporting Comment'),
                ('tool_proficiency_ads_automation_crm_comment', 'Tool Proficiency Ads Automation CRM Comment'),
                ('creativity_experimentation_comment', 'Creativity Experimentation Comment'),
            ],
            'developer': [
                ('technical_competency_comment', 'Technical Competency Comment'),
                ('code_quality_standards_comment', 'Code Quality Standards Comment'),
                ('debugging_root_cause_comment', 'Debugging Root Cause Comment'),
                ('requirement_understanding_accuracy_comment', 'Requirement Understanding Accuracy Comment'),
                ('estimation_accuracy_reliability_comment', 'Estimation Accuracy Reliability Comment'),
            ],
            'team_lead': [
                ('task_planning_allocation_comment', 'Task Planning Allocation Comment'),
                ('delivery_predictability_comment', 'Delivery Predictability Comment'),
                ('mentoring_technical_guidance_comment', 'Mentoring Technical Guidance Comment'),
                ('risk_identification_escalation_comment', 'Risk Identification Escalation Comment'),
                ('stakeholder_client_communication_comment', 'Stakeholder Client Communication Comment'),
            ],
            'project_manager': [
                ('project_planning_timeline_control_comment', 'Project Planning Timeline Control Comment'),
                ('scope_change_management_comment', 'Scope Change Management Comment'),
                ('risk_dependency_management_comment', 'Risk Dependency Management Comment'),
                ('stakeholder_communication_comment', 'Stakeholder Communication Comment'),
                ('status_reporting_accuracy_comment', 'Status Reporting Accuracy Comment'),
            ],
            'tester': [
                ('test_case_design_quality_comment', 'Test Case Design Quality Comment'),
                ('bug_reporting_clarity_comment', 'Bug Reporting Clarity Comment'),
                ('coverage_edge_case_thinking_comment', 'Coverage Edge Case Thinking Comment'),
                ('regression_discipline_comment', 'Regression Discipline Comment'),
                ('quality_ownership_comment', 'Quality Ownership Comment'),
            ],
            'hr': [
                ('hiring_pipeline_management_comment', 'Hiring Pipeline Management Comment'),
                ('policy_compliance_documentation_comment', 'Policy Compliance Documentation Comment'),
                ('employee_issue_handling_comment', 'Employee Issue Handling Comment'),
                ('process_improvement_initiative_comment', 'Process Improvement Initiative Comment'),
                ('confidentiality_professionalism_comment', 'Confidentiality Professionalism Comment'),
            ],
        }
        for rec in self:
            role_fields = ROLE_FIELDS.get(rec.role, [])
            for field_name, label in role_fields:
                rec._field_required(rec[field_name], label)

    @api.constrains(
        # Common
        "communication_clarity_rating","communication_clarity_comment",
        "accountability_ownership_rating","accountability_ownership_comment",
        "deadline_discipline_rating","deadline_discipline_comment",
        "work_quality_rating","work_quality_comment",
        "process_adherence_rating","process_adherence_comment",
        "learning_improvement_rating","learning_improvement_comment",

        # Sales
        "prospecting_pipeline_discipline_rating","prospecting_pipeline_discipline_comment",
        "follow_up_deal_progression_rating","follow_up_deal_progression_comment",
        "discovery_questioning_quality_rating","discovery_questioning_quality_comment",
        "objection_handling_negotiation_rating","objection_handling_negotiation_comment",
        "forecast_accuracy_revenue_ownership_rating","forecast_accuracy_revenue_ownership_comment",

        # Marketing
        "campaign_planning_execution_rating","campaign_planning_execution_comment",
        "lead_quality_contribution_rating","lead_quality_contribution_comment",
        "performance_tracking_reporting_rating","performance_tracking_reporting_comment",
        "tool_proficiency_ads_automation_crm_rating","tool_proficiency_ads_automation_crm_comment",
        "creativity_experimentation_rating","creativity_experimentation_comment",

        # Developer
        "technical_competency_rating","technical_competency_comment",
        "code_quality_standards_rating","code_quality_standards_comment",
        "debugging_root_cause_rating","debugging_root_cause_comment",
        "requirement_understanding_accuracy_rating","requirement_understanding_accuracy_comment",
        "estimation_accuracy_reliability_rating","estimation_accuracy_reliability_comment",

        # Team lead
        "task_planning_allocation_rating","task_planning_allocation_comment",
        "delivery_predictability_rating","delivery_predictability_comment",
        "mentoring_technical_guidance_rating","mentoring_technical_guidance_comment",
        "risk_identification_escalation_rating","risk_identification_escalation_comment",
        "stakeholder_client_communication_rating","stakeholder_client_communication_comment",

        # PM
        "project_planning_timeline_control_rating","project_planning_timeline_control_comment",
        "scope_change_management_rating","scope_change_management_comment",
        "risk_dependency_management_rating","risk_dependency_management_comment",
        "stakeholder_communication_rating","stakeholder_communication_comment",
        "status_reporting_accuracy_rating","status_reporting_accuracy_comment",

        # QA
        "test_case_design_quality_rating","test_case_design_quality_comment",
        "bug_reporting_clarity_rating","bug_reporting_clarity_comment",
        "coverage_edge_case_thinking_rating","coverage_edge_case_thinking_comment",
        "regression_discipline_rating","regression_discipline_comment",
        "quality_ownership_rating","quality_ownership_comment",

        # HR
        "hiring_pipeline_management_rating","hiring_pipeline_management_comment",
        "policy_compliance_documentation_rating","policy_compliance_documentation_comment",
        "employee_issue_handling_rating","employee_issue_handling_comment",
        "process_improvement_initiative_rating","process_improvement_initiative_comment",
        "confidentiality_professionalism_rating","confidentiality_professionalism_comment",
    )
    def _check_comments_mandatory_if_low(self):
        for rec in self:
            # Common comment min length checks
            rec._check_comment_min_length(rec.communication_clarity_comment, "Communication Clarity Comment")
            rec._check_comment_min_length(rec.accountability_ownership_comment, "Accountability Ownership Comment")
            rec._check_comment_min_length(rec.deadline_discipline_comment, "Deadline Discipline Comment")
            rec._check_comment_min_length(rec.work_quality_comment, "Work Quality Comment")
            rec._check_comment_min_length(rec.process_adherence_comment, "Process Adherence Comment")
            rec._check_comment_min_length(rec.learning_improvement_comment, "Learning Improvement Comment")

            # Common checks
            rec._comment_required(rec.communication_clarity_rating, rec.communication_clarity_comment, "Communication Clarity")
            rec._comment_required(rec.accountability_ownership_rating, rec.accountability_ownership_comment, "Accountability / Ownership")
            rec._comment_required(rec.deadline_discipline_rating, rec.deadline_discipline_comment, "Deadline Discipline")
            rec._comment_required(rec.work_quality_rating, rec.work_quality_comment, "Work Quality")
            rec._comment_required(rec.process_adherence_rating, rec.process_adherence_comment, "Process Adherence")
            rec._comment_required(rec.learning_improvement_rating, rec.learning_improvement_comment, "Learning & Improvement Attitude")

            # Role-specific checks only for the selected role
            if rec.role == "sales":
                rec._comment_required(rec.prospecting_pipeline_discipline_rating, rec.prospecting_pipeline_discipline_comment, "Prospecting & Pipeline Discipline")
                rec._comment_required(rec.follow_up_deal_progression_rating, rec.follow_up_deal_progression_comment, "Follow-Up & Deal Progression")
                rec._comment_required(rec.discovery_questioning_quality_rating, rec.discovery_questioning_quality_comment, "Discovery & Questioning Quality")
                rec._comment_required(rec.objection_handling_negotiation_rating, rec.objection_handling_negotiation_comment, "Objection Handling & Negotiation")
                rec._comment_required(rec.forecast_accuracy_revenue_ownership_rating, rec.forecast_accuracy_revenue_ownership_comment, "Forecast Accuracy & Revenue Ownership")

            elif rec.role == "marketing":
                rec._comment_required(rec.campaign_planning_execution_rating, rec.campaign_planning_execution_comment, "Campaign Planning & Execution")
                rec._comment_required(rec.lead_quality_contribution_rating, rec.lead_quality_contribution_comment, "Lead Quality Contribution")
                rec._comment_required(rec.performance_tracking_reporting_rating, rec.performance_tracking_reporting_comment, "Performance Tracking & Reporting")
                rec._comment_required(rec.tool_proficiency_ads_automation_crm_rating, rec.tool_proficiency_ads_automation_crm_comment, "Tool Proficiency (Ads/Automation/CRM)")
                rec._comment_required(rec.creativity_experimentation_rating, rec.creativity_experimentation_comment, "Creativity & Experimentation")

            elif rec.role == "developer":
                rec._comment_required(rec.technical_competency_rating, rec.technical_competency_comment, "Technical Competency")
                rec._comment_required(rec.code_quality_standards_rating, rec.code_quality_standards_comment, "Code Quality & Standards")
                rec._comment_required(rec.debugging_root_cause_rating, rec.debugging_root_cause_comment, "Debugging / Root Cause Ability")
                rec._comment_required(rec.requirement_understanding_accuracy_rating, rec.requirement_understanding_accuracy_comment, "Requirement Understanding Accuracy")
                rec._comment_required(rec.estimation_accuracy_reliability_rating, rec.estimation_accuracy_reliability_comment, "Estimation Accuracy & Reliability")

            elif rec.role == "team_lead":
                rec._comment_required(rec.task_planning_allocation_rating, rec.task_planning_allocation_comment, "Task Planning & Allocation")
                rec._comment_required(rec.delivery_predictability_rating, rec.delivery_predictability_comment, "Delivery Predictability")
                rec._comment_required(rec.mentoring_technical_guidance_rating, rec.mentoring_technical_guidance_comment, "Mentoring & Technical Guidance")
                rec._comment_required(rec.risk_identification_escalation_rating, rec.risk_identification_escalation_comment, "Risk Identification & Escalation")
                rec._comment_required(rec.stakeholder_client_communication_rating, rec.stakeholder_client_communication_comment, "Stakeholder / Client Communication")

            elif rec.role == "project_manager":
                rec._comment_required(rec.project_planning_timeline_control_rating, rec.project_planning_timeline_control_comment, "Project Planning & Timeline Control")
                rec._comment_required(rec.scope_change_management_rating, rec.scope_change_management_comment, "Scope & Change Management")
                rec._comment_required(rec.risk_dependency_management_rating, rec.risk_dependency_management_comment, "Risk & Dependency Management")
                rec._comment_required(rec.stakeholder_communication_rating, rec.stakeholder_communication_comment, "Stakeholder Communication")
                rec._comment_required(rec.status_reporting_accuracy_rating, rec.status_reporting_accuracy_comment, "Status Reporting Accuracy")

            elif rec.role == "tester":
                rec._comment_required(rec.test_case_design_quality_rating, rec.test_case_design_quality_comment, "Test Case Design Quality")
                rec._comment_required(rec.bug_reporting_clarity_rating, rec.bug_reporting_clarity_comment, "Bug Reporting Clarity")
                rec._comment_required(rec.coverage_edge_case_thinking_rating, rec.coverage_edge_case_thinking_comment, "Coverage & Edge Case Thinking")
                rec._comment_required(rec.regression_discipline_rating, rec.regression_discipline_comment, "Regression Discipline")
                rec._comment_required(rec.quality_ownership_rating, rec.quality_ownership_comment, "Quality Ownership")

            elif rec.role == "hr":
                rec._comment_required(rec.hiring_pipeline_management_rating, rec.hiring_pipeline_management_comment, "Hiring Pipeline Management")
                rec._comment_required(rec.policy_compliance_documentation_rating, rec.policy_compliance_documentation_comment, "Policy Compliance & Documentation")
                rec._comment_required(rec.employee_issue_handling_rating, rec.employee_issue_handling_comment, "Employee Issue Handling")
                rec._comment_required(rec.process_improvement_initiative_rating, rec.process_improvement_initiative_comment, "Process Improvement Initiative")
                rec._comment_required(rec.confidentiality_professionalism_rating, rec.confidentiality_professionalism_comment, "Confidentiality & Professionalism")
