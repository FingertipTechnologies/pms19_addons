# -*- coding: utf-8 -*-
"""Static checks on the dashboard assets (no database, no browser)."""
import os
import re

from odoo.tests.common import BaseCase, tagged

BASE = os.path.join(os.path.dirname(__file__), '..', 'static', 'src')


def read(*parts):
    with open(os.path.join(BASE, *parts)) as handle:
        return handle.read()


def templates():
    folder = os.path.join(BASE, 'xml')
    return {name: read('xml', name) for name in sorted(os.listdir(folder)) if name.endswith('.xml')}


@tagged('post_install', '-at_install', 'adoption_pure')
class TestDashboardAssets(BaseCase):

    def test_theme_is_a_single_blue_with_no_gradients(self):
        scss = read('scss', 'adoption_dashboard.scss')
        self.assertNotIn('linear-gradient(', scss)
        self.assertRegex(scss, r'--ad-grad:\s*#[0-9a-fA-F]{6};')
        self.assertIsNone(re.search(r'#7c3aed|#8b5cf6|124,\s*58,\s*237', scss), 'no purple left')

    def test_small_cards_are_five_per_row(self):
        scss = read('scss', 'adoption_dashboard.scss')
        self.assertRegex(scss, r'\.ad-kpis-sm\s*\{\s*grid-template-columns:\s*repeat\(5,')

    def test_dashboard_has_its_own_scroll_bars(self):
        scss = read('scss', 'adoption_dashboard.scss')
        self.assertRegex(scss, r'\.ad-main\s*\{[^}]*overflow-y:\s*scroll')
        self.assertIn('::-webkit-scrollbar', scss)
        self.assertIn('scrollbar-width: thin', scss)

    def test_activity_log_has_the_five_cards(self):
        xml = read('xml', 'adoption_activity_log.xml')
        for label in ('Created', 'Updated', 'Deleted', 'User-initiated', 'Automated'):
            self.assertRegex(xml, r'ad-kpi-label">%s<' % label)
        self.assertEqual(xml.count('class="ad-card ad-kpi"'), 5)

    def test_every_model_filter_says_all_models_and_field_adoption_needs_no_choice(self):
        shell = read('xml', 'adoption_dashboard.xml')
        self.assertIn('All models</option>', shell)
        self.assertNotIn('Choose a model', ' '.join(templates().values()))
        js = read('js', 'adoption_field_adoption.js')
        self.assertNotIn('props.model ?', js, 'must not be gated on a chosen model')

    def test_no_javascript_globals_inside_templates(self):
        # OWL templates cannot call String(), Number(), Math.x ... (this crashed the dashboard once)
        pattern = re.compile(r"[^.\w'\"](String|Number|Math|JSON|parseInt|parseFloat|Date|Object|Array|isNaN)[.(]")
        for name, source in templates().items():
            for line in source.splitlines():
                if 'type="date"' in line:
                    continue
                self.assertIsNone(pattern.search(line), '%s: %s' % (name, line.strip()))

    def test_sidebar_has_no_detail_lists(self):
        self.assertNotIn('Detail lists', templates()['adoption_dashboard.xml'])
