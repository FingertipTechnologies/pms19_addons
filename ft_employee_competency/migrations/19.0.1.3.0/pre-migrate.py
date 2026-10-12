def migrate(cr, version):
    """Review cycles move to the specification's Draft -> Open -> Closed.

    'Assessment Running' was an Open cycle with its assessments generated, so
    it maps to Open; 'Completed' is what the specification calls Closed.
    """
    cr.execute("""
        UPDATE employee_competency_cycle
           SET state = CASE state
                           WHEN 'running' THEN 'open'
                           WHEN 'done' THEN 'closed'
                       END
         WHERE state IN ('running', 'done')
    """)
