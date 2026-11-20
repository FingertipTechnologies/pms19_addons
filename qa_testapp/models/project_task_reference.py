import re

from odoo import api, fields, models


class ProjectTask(models.Model):
    _inherit = 'project.task'
    _rec_names_search = ['name', 'qa_task_reference']

    qa_task_reference = fields.Char(string='Task ID', readonly=True, copy=False, index=True)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for task in records:
            code = re.sub(r'[^A-Z0-9]', '', (task.project_id.name or '').upper())[:5] or 'TASK'
            task.qa_task_reference = 'TASK-%05d' % task.id
        return records

    def init(self):
        # Backfill existing tasks once; preserve references after project renames.abc
        self.env.cr.execute("""
            UPDATE project_task AS task
               SET qa_task_reference = COALESCE(
                       NULLIF(LEFT(REGEXP_REPLACE(UPPER(COALESCE(project.name->>'en_US', '')),
                           '[^A-Z0-9]', '', 'g'), 5), ''), 'TASK')
                   || '-' || LPAD(task.id::text, GREATEST(5, LENGTH(task.id::text)), '0')
              FROM project_project AS project
             WHERE task.project_id = project.id
               AND (task.qa_task_reference IS NULL OR task.qa_task_reference = '')
        """)
        self.env.cr.execute("""
            UPDATE project_task SET qa_task_reference = 'TASK-' ||
                LPAD(id::text, GREATEST(5, LENGTH(id::text)), '0')
            WHERE qa_task_reference IS NULL OR qa_task_reference = ''
        """)
