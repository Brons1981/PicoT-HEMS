from picot.v2.economic_standby import cheap_contiguous_blocks


def test_disconnected_cheap_quarters_are_separate_complete_alternatives():
    blocks = cheap_contiguous_blocks({0: 0.50, 1: 0.20, 2: 0.60, 3: 0.21, 4: 0.55})
    assert (1, 1) in blocks and (3, 3) in blocks
    assert (0, 1) in blocks and (3, 4) in blocks
    assert (0, 4) in blocks
    assert all(start <= end for start, end in blocks)
    assert (1, 3) not in blocks  # a high-priced connector is not a cheap block


def test_protected_boundary_never_connects_blocks():
    blocks = cheap_contiguous_blocks({0: 0.20, 1: 0.21, 3: 0.20, 4: 0.21})
    assert (0, 1) in blocks and (3, 4) in blocks
    assert all(not (start < 2 < end) for start, end in blocks)


def test_monotonic_prices_offer_each_cheap_suffix_with_linear_candidate_bound():
    prices = {n: 1 - n / 100 for n in range(60)}
    blocks = cheap_contiguous_blocks(prices)
    assert set(blocks) == {(start, 59) for start in range(60)}
    assert len(blocks) <= 2 * len(prices)


def test_support_floor_and_profitable_single_block_are_valid_choices(tmp_path):
    from dataclasses import replace

    from test_daily_main_charge_windows import inputs
    from test_market_revision_comparison import scenario

    from picot.domain.daily_reference_intent import DailyStorageIntent as Intent
    from picot.domain.evaluation import CandidateValidity
    from picot.planner.mep_candidate_outcomes import produce_main_charge_portfolio
    from picot.v2.daily_bridge import energy_deficits
    from picot.v2.independent_daily_reference_adapter import IndependentDailyReferenceAdapter
    from picot.v2.independent_daily_tariff_adapter import IndependentDailyTariffAdapter

    _, snapshot, _ = scenario(tmp_path, soc=0.3)
    snapshot = replace(
        snapshot,
        price_points=tuple(
            replace(p, value_eur_per_kwh=0.02 if 4 <= n < 8 else 0.6 if n < 20 else 0.1)
            for n, p in enumerate(snapshot.price_points)
        ),
    )
    adapter = IndependentDailyReferenceAdapter()
    conversion = inputs()["conversion_model"]
    trigger = adapter.bridge_assessment(snapshot=snapshot, conversion_model=conversion).trigger
    windows = adapter.bridge_windows(
        snapshot=snapshot, trigger=trigger, conversion_model=conversion
    )
    tariffs = IndependentDailyTariffAdapter().build(
        snapshot, horizon_end=windows.windows[0].schedule.horizon_end
    )
    portfolio = produce_main_charge_portfolio(
        snapshot=snapshot, windows=windows, tariffs=tariffs, opportunity_ids=()
    )
    reference = next(
        w for w in windows.windows if w.schedule.schedule_id.startswith("bridge-economic-support:")
    )
    assert any(
        i.deficit_wh > 0
        for i in energy_deficits(
            reference.projection,
            reference.schedule,
            until=trigger.next_starts_at,
            maximum_discharge_output_power_w=2400,
        )
    )
    valid = {
        o.candidate_id
        for o in portfolio.outcome_set.outcomes
        if o.validity is CandidateValidity.VALID
    }
    support_sources = [s for s in portfolio.sources if s.window is reference]
    assert support_sources and support_sources[0].candidate_id in valid
    beneficial = []
    for source in portfolio.sources:
        if source.window is None or source.candidate_id not in valid:
            continue
        before = [
            i for i in source.window.schedule.intervals if i.ends_at <= trigger.next_starts_at
        ]
        groups = sum(
            i.intent is Intent.STANDBY and (n == 0 or before[n - 1].intent is not Intent.STANDBY)
            for n, i in enumerate(before)
        )
        assert groups <= 1
        if groups:
            assert source.financial.cash_result_eur > support_sources[0].financial.cash_result_eur
            beneficial.append(source)
    assert beneficial

    from picot.domain.execution_primitive import ExecutionPrimitive as Primitive
    from picot.v2.zendure_mode_capabilities import (
        ZendureModeCapabilityEvidence,
        ZendureModeMapping,
    )

    modes = (
        ZendureModeMapping("support", (Primitive.BALANCE_DISCHARGE_ONLY,)),
        ZendureModeMapping("standby", (Primitive.STANDBY,)),
    )
    evidence = ZendureModeCapabilityEvidence(
        snapshot.captured_at,
        "input_select.mode",
        "battery-capability",
        "battery",
        "support",
        "available",
        None,
        ("support", "standby"),
        (),
        modes,
    )
    observed = produce_main_charge_portfolio(
        snapshot=replace(snapshot, storage_mode_capability_evidence=evidence),
        windows=windows,
        tariffs=tariffs,
        opportunity_ids=(),
    )
    counts = {o.candidate_id: o.expected_switching_count for o in observed.outcome_set.outcomes}
    original = {o.candidate_id: o.expected_switching_count for o in portfolio.outcome_set.outcomes}
    by_path = {p.path_id: p for p in portfolio.candidate_set.energy_paths}
    paths = {c.candidate_id: by_path[c.energy_path_id] for c in portfolio.candidate_set.candidates}
    immediate = [
        cid for cid, path in paths.items() if path.segments[0].primitive is Primitive.STANDBY
    ]
    assert immediate
    assert all(counts[cid] == original[cid] + 1 for cid in immediate)
    assert counts[support_sources[0].candidate_id] == original[support_sources[0].candidate_id]
