{
    "name": "Employee Monthly Review",
    "version": "19.0.1.0.0",
    "category": "Human Resources",
    "depends": ["hr"],
    "data": [
        "security/employee_review_security.xml",
        "security/ir.model.access.csv",
        "views/review_views.xml",
    ],
    'images': ['static/description/performance_review.png'],
    "installable": True,
    "application": True,
}
