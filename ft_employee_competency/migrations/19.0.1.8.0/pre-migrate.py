"""19.0.1.8.0 pre-migration: adopt master data rows that exist without xmlid.

A database may carry the master data (rating levels, categories,
competencies) created by hand or under a lost xmlid. The noupdate data
file then tries to CREATE them again on upgrade and hits the unique
constraints (e.g. category name "Leadership"). Before the data loads,
point every missing ft_employee_competency.<id> xmlid at the row that
matches its unique key: level by rating, category by name, competency by
code. Rows that truly do not exist are created by the data file as usual.
"""
import logging

from lxml import etree

from odoo.tools.misc import file_path

_logger = logging.getLogger(__name__)

MODULE = 'ft_employee_competency'
DATA_FILE = 'ft_employee_competency/data/competency_master_data.xml'

# model -> (table, data field holding the unique key, SQL match on that key)
KEYS = {
    'employee.competency.level': (
        'employee_competency_level', 'rating', "rating = %s::int"),
    'employee.competency.category': (
        'employee_competency_category', 'name', "name->>'en_US' = %s"),
    'employee.competency': (
        'employee_competency', 'code', "code = %s"),
}


def migrate(cr, version):
    try:
        tree = etree.parse(file_path(DATA_FILE))
    except Exception:  # noqa: BLE001 - a missing file is not this script's job
        _logger.exception("%s: cannot read %s; skipping adoption", MODULE, DATA_FILE)
        return
    adopted = 0
    for rec in tree.iter('record'):
        model = rec.get('model')
        xmlid = rec.get('id')
        if model not in KEYS or not xmlid:
            continue
        table, key_field, match = KEYS[model]
        key = rec.find("field[@name='%s']" % key_field)
        if key is None or not (key.text or '').strip():
            continue
        cr.execute("SELECT 1 FROM ir_model_data WHERE module = %s AND name = %s",
                   (MODULE, xmlid))
        if cr.fetchone():
            continue
        cr.execute("SELECT id FROM %s WHERE %s ORDER BY id LIMIT 1" % (table, match),
                   (key.text.strip(),))
        row = cr.fetchone()
        if not row:
            continue
        cr.execute("""
            INSERT INTO ir_model_data (module, name, model, res_id, noupdate)
            VALUES (%s, %s, %s, %s, true)
        """, (MODULE, xmlid, model, row[0]))
        adopted += 1
        _logger.info("%s: xmlid %s adopted existing %s id %s (%s=%s)",
                     MODULE, xmlid, model, row[0], key_field, key.text.strip())
    if adopted:
        _logger.info("%s: adopted %d master data row(s) without xmlid", MODULE, adopted)
