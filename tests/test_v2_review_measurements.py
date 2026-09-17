from __future__ import annotations

import gzip
import json
from dataclasses import replace
from datetime import timedelta

import pytest
from test_v2_grid_charge_review import START, evaluate, history

from picot.v2.power_history import PowerHistoryPoint
from picot.v2.review_measurements import measurement_coverage, save_measurements


def test_real_one_second_soc_outage_has_exact_source_and_span():
    h = history()
    at = START + timedelta(minutes=30)
    h = replace(h, series=tuple(
        replace(s, points=(s.points[0], PowerHistoryPoint(at, float('nan'), 'gap'),
                           PowerHistoryPoint(at + timedelta(seconds=1), 20, 'restored'),
                           *s.points[1:])) if s.role == 'storage_soc' else s
        for s in h.series
    ))
    result = evaluate(h)
    assert result['status'] == 'incomplete'
    assert 'avoidable_grid_charge_kwh' not in result
    soc = result['measurement_coverage']['storage_soc']
    assert soc['source_entity_id'] == 'sensor.storage_soc'
    assert soc['gaps'] == [{
        'reason': 'measurement_unavailable', 'starts_at': at.isoformat(),
        'ends_at': (at + timedelta(seconds=1)).isoformat(), 'duration_seconds': 1,
    }]


def test_unchanged_recorder_state_is_not_a_gap_but_polling_gap_is():
    h = history()
    h = replace(h, series=tuple(
        replace(s, points=s.points[:1], history_semantics='sampled_linear')
        if s.role == 'household_load' else replace(s, points=s.points[:1])
        for s in h.series
    ))
    coverage = measurement_coverage(h)
    assert coverage['storage_soc']['gap_count'] == 0
    assert coverage['pv_generation']['gap_count'] == 0
    assert coverage['household_load']['gaps'][0]['reason'] == 'household_measurement_tail_missing'


def test_missing_series_and_missing_anchor_are_distinguished():
    h = history()
    h = replace(h, series=tuple(
        replace(s, points=s.points[1:]) if s.role == 'storage_soc' else s
        for s in h.series if s.role != 'pv_generation'
    ))
    coverage = measurement_coverage(h)
    assert coverage['pv_generation']['gaps'][0]['reason'] == 'missing_measured_series'
    assert coverage['storage_soc']['gaps'][0]['reason'] == 'measurement_start_missing'


def test_archive_preserves_raw_values_timestamps_and_gaps_across_failed_read(tmp_path):
    h = history()
    h = replace(h, series=tuple(
        replace(s, points=(s.points[0], replace(s.points[1], power_w=float('nan')),
                           *s.points[2:])) if s.role == 'pv_generation' else s
        for s in h.series
    ))
    path = tmp_path / 'measurements.json.gz'
    assert save_measurements(path, h)['status'] == 'available'
    before = path.read_bytes()
    with gzip.open(path, 'rt') as stream:
        raw = json.load(stream, parse_constant=lambda v: pytest.fail(f'Invalid JSON {v}'))
    pv = next(s for s in raw['series'] if s['role'] == 'pv_generation')
    assert pv['points'][1]['power_w'] is None
    assert pv['points'][1]['evidence_id'] == 'pv_generation-1'
    assert pv['points'][0]['sampled_at'] == START.isoformat()
    assert raw['ends_at'] == h.ends_at.isoformat()
    assert save_measurements(path, replace(h, status='unavailable', error='TimeoutError'))[
        'status'] == 'unavailable'
    assert path.read_bytes() == before
    assert not list(tmp_path.glob('*.writing'))
