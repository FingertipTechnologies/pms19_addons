# -*- coding: utf-8 -*-
"""The adoption score: six weighted components, each normalised against the
organisation's own 75th percentile.

Pure Python.  Faithful to the original Salesforce ``AdoptionScoreCalculator``:

    Presence            15   active days
    Data activity       20   records created + updated
    Process compliance  25   edits to fields flagged as meaningful
    Feature adoption    15   objects used + reports + dashboards opened
    Engagement          15   active minutes in the UI
    Data quality        10   distinct fields maintained per record touched

    component = min(1, value / org_p75)          (original stores x100)
    total     = sum(component * weight)           (0..100)

Deliberate differences from the original
----------------------------------------
Original: a zero p75 is replaced by ``1``, so anyone with a value >= 1 scores
a *full* component.  That hands out free points whenever fewer than a quarter
of users have the metric at all (typical for Engagement on day one).  Here:

* p75 > 0                    -> benchmark = p75                 (as original)
* p75 == 0, someone has > 0  -> benchmark = best observed value (only the top
                                performer reaches 1.0; no free full marks)
* nobody has any value       -> component is *unavailable*: scores 0 and is
                                flagged in the notes (no re-weighting, so the
                                weights stay exactly the original's).

p75 uses the original's lower nearest-rank: ``sorted[floor(0.75*(n-1))]``.
Only users with at least one active day form the reference population.
"""
import math
from dataclasses import dataclass

WEIGHTS = {
    'presence': 15,
    'data_activity': 20,
    'process_compliance': 25,
    'feature_adoption': 15,
    'engagement': 15,
    'data_quality': 10,
}
COMPONENTS = tuple(WEIGHTS)
PERCENTILE = 0.75
SMALL_POPULATION = 4     # below this, p75 is basically the user's own value

BAND_POWER_USER = 'power_user'
BAND_HEALTHY = 'healthy'
BAND_NEEDS_IMPROVEMENT = 'needs_improvement'
BAND_AT_RISK = 'at_risk'
BAND_INACTIVE = 'inactive'


@dataclass
class Totals:
    user_id: int = 0
    active_days: int = 0
    records_touched: float = 0.0
    meaningful_edits: float = 0.0
    field_edits: float = 0.0
    distinct_fields: float = 0.0
    objects_used: float = 0.0
    reports_and_dashboards: float = 0.0
    active_minutes: float = 0.0
    logins: float = 0.0


def percentile(values, q=PERCENTILE):
    """Lower nearest-rank percentile, identical to the original. Empty -> 0."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return float(ordered[int(math.floor(q * (len(ordered) - 1)))])


def fields_per_record(totals):
    """Field breadth per record touched; 0 (never a division by zero)."""
    if totals.records_touched <= 0:
        return 0.0
    return totals.distinct_fields / totals.records_touched


def component_values(totals):
    return {
        'presence': float(totals.active_days),
        'data_activity': float(totals.records_touched),
        'process_compliance': float(totals.meaningful_edits),
        'feature_adoption': float(totals.objects_used + totals.reports_and_dashboards),
        'engagement': float(totals.active_minutes),
        'data_quality': float(fields_per_record(totals)),
    }


def compute_benchmarks(all_totals):
    """Reference value per component from the *active* population.

    Returns ``{component: {'value': float|None, 'method': str}, '_population': n}``.
    """
    population = [t for t in all_totals if t.active_days > 0]
    per_component = {name: [] for name in COMPONENTS}
    for totals in population:
        for name, value in component_values(totals).items():
            per_component[name].append(value)

    benchmarks = {'_population': len(population)}
    for name, values in per_component.items():
        p75 = percentile(values)
        if p75 > 0:
            benchmarks[name] = {'value': p75, 'method': 'p75'}
            continue
        best = max(values) if values else 0.0
        if best > 0:
            benchmarks[name] = {'value': best, 'method': 'max_fallback'}
        else:
            benchmarks[name] = {'value': None, 'method': 'unavailable'}
    return benchmarks


def normalise(value, benchmark):
    """min(1, value / benchmark); 0 when the benchmark is missing or <= 0."""
    if benchmark is None or benchmark <= 0:
        return 0.0
    return max(0.0, min(1.0, float(value) / benchmark))


def band(total, active_days):
    """Adoption band.  ``inactive`` means *no qualifying activity*, which is
    different from a valid low score (``at_risk``)."""
    if active_days <= 0:
        return BAND_INACTIVE
    if total >= 90:
        return BAND_POWER_USER
    if total >= 70:
        return BAND_HEALTHY
    if total >= 50:
        return BAND_NEEDS_IMPROVEMENT
    return BAND_AT_RISK


def score_user(totals, benchmarks):
    """Score one user: weighted component scores (each ``0..weight``),
    ``total_score`` (0..100), ``adoption_band`` and diagnostic ``notes``."""
    values = component_values(totals)
    result, notes, total = {}, [], 0.0
    for name in COMPONENTS:
        info = benchmarks.get(name, {})
        contribution = normalise(values[name], info.get('value')) * WEIGHTS[name]
        result['%s_score' % name] = round(contribution, 2)
        total += contribution
        method = info.get('method', 'unavailable')
        if method == 'unavailable':
            notes.append('%s: no reference data in this period (scored 0)' % name)
        elif method == 'max_fallback':
            notes.append('%s: p75 is 0, benchmarked against the best performer' % name)
    population = benchmarks.get('_population', 0)
    if 0 < population < SMALL_POPULATION:
        notes.append('small reference population (%d active users)' % population)
    total = max(0.0, min(100.0, total))
    result['total_score'] = round(total, 2)
    result['adoption_band'] = band(total, totals.active_days)
    result['notes'] = '; '.join(notes)
    return result
