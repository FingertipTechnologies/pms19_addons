{
    'name': 'HR Employee Details',
    # 19.0.1.4.0: every employee can change their own profile photo on their
    #   public employee profile (Employees app); it also updates their user
    #   avatar. Python/view only, no migration.
    'version': '19.0.1.4.0',
    'category': 'Human Resources',
    'summary': 'Extended Employee Details - Aadhar, PAN, Family, Bank, References',
    'description': """
        Adds additional employee fields inside Personal tab:
        - Aadhar, PAN, UAN/PF numbers
        - Present & Permanent Address
        - Family Particulars
        - Bank Account Details
        - Employee References

        The same Personal page is shown on the public employee profile
        (hr.employee.public). Each employee sees and edits only their own
        details there, including their profile photo; HR Officers and
        administrators see everyone's.
    """,
    'author': 'Fingertip Plus',
    'depends': ['hr'],
    'data': [
        'security/ir.model.access.csv',
        'security/hr_employee_details_security.xml',
        'views/hr_employee_views.xml',
        'views/hr_employee_public_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
