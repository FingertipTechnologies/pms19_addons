#!/usr/bin/env bash
# Runs the browser-logic unit tests in plain Node (no Odoo, no browser).
# The sources are ES modules named .js (Odoo's convention); Node needs .mjs,
# so they are copied temporarily next to the originals and removed afterwards.
set -euo pipefail
cd "$(dirname "$0")/../.."
JS=static/src/js
trap 'rm -f $JS/adoption_timer.mjs $JS/adoption_navigation.mjs $JS/adoption_chart_math.mjs' EXIT
cp $JS/adoption_timer.js $JS/adoption_timer.mjs
cp $JS/adoption_navigation.js $JS/adoption_navigation.mjs
cp $JS/adoption_chart_math.js $JS/adoption_chart_math.mjs
node --test tests/js/test_timer.mjs tests/js/test_navigation.mjs tests/js/test_chart_math.mjs
