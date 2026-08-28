from pathlib import Path

ROOT = Path(__file__).parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_live_runtime_contains_one_canonical_planner_route() -> None:
    source = _source("src/picot/v2/live_runtime.py")

    forbidden_parallel_components = (
        "CandidateEngine",
        "IndependentDailyObserverRuntime",
        "IndependentDailyObserverWorker",
        "MarketDailyPlannerWorker",
        "PlannerComparisonLedger",
        "derive_storage_requirements",
    )

    assert all(
        component not in source
        for component in forbidden_parallel_components
    )
    assert source.count("CanonicalPipeline(") == 1
    assert source.count("CanonicalExecutionRuntime(") == 1


def test_mep_has_no_private_execution_or_commitment_layer() -> None:
    source = _source("src/picot/v2/market_daily_runtime.py")

    forbidden_private_authority = (
        "class MarketDailyExecutionRuntime",
        "def _resolve_commitment",
        "def _challenger_is_better",
        "def _persist_action_commitment",
        "HomeAssistantCanonicalModeAdapter",
    )

    assert all(
        component not in source
        for component in forbidden_private_authority
    )


def test_addon_exposes_one_execution_authority_option() -> None:
    config = _source("picot_hems/config.yaml")

    assert 'execution_mode: "live"' in config
    assert "execution_mode: list(observer|live)" in config
    assert "canonical_execution_mode:" not in config
    assert "market_daily_execution_mode:" not in config
    assert "live_pv_canary_mode:" not in config


def test_mep_planner_contains_no_vendor_mode_policy() -> None:
    source = _source("src/picot/planner/market_daily_planner.py")

    forbidden_vendor_modes = (
        "Nul op de meter",
        "Alleen slim ontladen",
        "Snel opladen",
        "Snel ontladen",
        "Standby",
    )

    assert all(mode not in source for mode in forbidden_vendor_modes)


def test_production_pipeline_contains_no_cp_fallback() -> None:
    source = _source("src/picot/v2/pipeline.py")

    forbidden_cp_owners = (
        "DelegatedStorageEvaluationEngine",
        "construct_pv_charge_only_candidate",
        "simulate_pv_charge_only_outcomes",
        "derive_storage_requirements",
    )

    assert all(owner not in source for owner in forbidden_cp_owners)
    assert "market_daily_planner_runtime: MarketDailyPlannerRuntime" in source
    assert "market_daily_planner_runtime: MarketDailyPlannerRuntime | None" not in source


def test_vendor_translation_exists_only_at_adapter_boundary() -> None:
    composition = _source("src/picot/v2/mep_canonical_pipeline.py")
    runtime = _source("src/picot/v2/canonical_execution_runtime.py")

    assert "def _vendor_mode" not in composition
    assert "mapping.vendor_mode" not in composition
    assert "planned_vendor_mode=_vendor_mode" not in composition
    assert "HomeAssistantCommandMapping(" in runtime


def test_dashboard_has_no_parallel_cp_ep_or_private_mep_presentation() -> None:
    source = _source("src/picot/v2/web_ui.py")

    assert "view.market_daily_planner" not in source
    assert "view.independent_daily_observer" not in source
    assert "planner_comparison_history" not in source
    assert "MEP-commitment" not in source
