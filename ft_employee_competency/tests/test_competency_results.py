from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCompetencyResults(TransactionCase):
    """BR-018 (employee skills) and BR-009 / BR-010 (previous level)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.job = cls.env['hr.job'].search([('name', '=', 'Salesforce Developer')], limit=1)
        if cls.job.competency_matrix_state != 'validated':
            cls.job.action_validate_competency_matrix()
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Competency Test Employee',
            'job_id': cls.job.id,
        })
        Cycle = cls.env['employee.competency.cycle']
        cls.q1 = Cycle.create({
            'name': 'Test Q1', 'date_from': '2030-01-01', 'date_to': '2030-03-31',
            'employee_ids': [(6, 0, cls.employee.ids)],
        })
        cls.q2 = Cycle.create({
            'name': 'Test Q2', 'date_from': '2030-04-01', 'date_to': '2030-06-30',
            'employee_ids': [(6, 0, cls.employee.ids)],
        })
        (cls.q1 | cls.q2).action_open()

    def _complete(self, assessment, final, self_rating=5):
        """Take an assessment through the whole workflow with the given final
        rating on every line."""
        for line in assessment.line_ids:
            line.write({'self_rating': self_rating})
        assessment.action_submit_self_review()
        for line in assessment.line_ids:
            line.write({'manager_rating': final, 'manager_comments': 'Evidence'})
        assessment.action_submit_manager_review()
        self.assertEqual(assessment.state, 'hr_review')
        assessment.action_hr_approve()
        self.assertEqual(assessment.state, 'done')

    def _current_skills(self):
        return self.employee.current_employee_skill_ids.filtered(
            lambda s: s.skill_id in self.job.competency_line_ids.competency_id.hr_skill_id
        )

    def test_skills_updated_only_on_completion(self):
        assessment = self.q1.action_generate_assessments()
        self.assertFalse(self._current_skills(), 'no skill before any review completes')
        for line in assessment.line_ids:
            line.write({'self_rating': 5})
        assessment.action_submit_self_review()
        self.assertFalse(self._current_skills(), 'a review in progress must not touch skills')

    def test_final_rating_written_and_updated_without_duplicates(self):
        first = self.q1.action_generate_assessments()
        self._complete(first, final=3, self_rating=5)
        skills = self._current_skills()
        self.assertEqual(len(skills), len(first.line_ids), 'one skill per competency')
        self.assertEqual(
            set(skills.mapped('skill_level_id.level_progress')), {60},
            'the FINAL rating (3), not the self rating (5), is written',
        )

        second = self.q2.action_generate_assessments()
        self._complete(second, final=4)
        skills = self._current_skills()
        self.assertEqual(len(skills), len(second.line_ids), 'updated, not duplicated')
        self.assertEqual(set(skills.mapped('skill_level_id.level_progress')), {80})

    def test_previous_level_follows_a_later_completion(self):
        # Q2 is raised while Q1 is still in progress - the usual order.
        first = self.q1.action_generate_assessments()
        second = self.q2.action_generate_assessments()
        self.assertFalse(any(second.line_ids.mapped('previous_rating')))

        self._complete(first, final=2)
        self.assertEqual(second.previous_assessment_id, first)
        self.assertEqual(set(second.line_ids.mapped('previous_rating')), {2})

        self._complete(second, final=4)
        self.assertEqual(set(second.line_ids.mapped('improvement_score')), {2})
