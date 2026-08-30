import json
import shutil
import subprocess
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from legacy_cp_pipeline import CanonicalPipeline

from picot.v2.contracts import (
    HouseholdLoadForecast,
    HouseholdLoadForecastInterval,
    PriceForecastPoint,
    PVEnergyTimeline,
    PVEnergyTimelineInterval,
)
from picot.v2.opportunity_engine import PriceOpportunityConfig
from picot.v2.power_history import (
    PowerHistoryPoint,
    PowerHistorySeries,
    PowerHistorySnapshot,
)
from picot.v2.projection import project
from picot.v2.web_ui import (
    DASHBOARD_HTML,
    WebViewStore,
    _power_history_display_points,
    _self_consumption_history_view,
    build_web_view,
)


def test_dashboard_embedded_javascript_is_syntactically_valid() -> None:
    node = shutil.which("node")
    if node is None:
        raise AssertionError("Node.js is required to validate dashboard JavaScript")

    script_start = DASHBOARD_HTML.index("<script>") + len("<script>")
    script_end = DASHBOARD_HTML.index("</script>", script_start)
    result = subprocess.run(
        [node, "--check"],
        input=DASHBOARD_HTML[script_start:script_end],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_web_view_serializes_nine_stages_and_full_pv_timeline() -> None:
    captured_at = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
    bootstrap = CanonicalPipeline().run(
        captured_at=captured_at
    ).planning_input
    starts_at = captured_at + timedelta(minutes=30)
    intervals = (
        PVEnergyTimelineInterval(
            interval_id="pv-interval-1",
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=30),
            pv_energy_wh=1200.0,
            forecast_lower_energy_wh=900.0,
            forecast_central_energy_wh=1200.0,
            forecast_upper_energy_wh=1500.0,
            forecast_range_status="available",
            forecast_range_source_fields=("pv_estimate10", "pv_estimate90"),
            forecast_range_method_version="solcast-range:v1",
            evidence_type="FORECAST",
            confidence=0.90,
            actual_evidence_ids=(),
            forecast_evidence_ids=("solcast-1",),
            conversion_method_version="solcast:v1",
        ),
        PVEnergyTimelineInterval(
            interval_id="pv-interval-2",
            starts_at=starts_at + timedelta(minutes=30),
            ends_at=starts_at + timedelta(minutes=60),
            pv_energy_wh=1350.0,
            forecast_lower_energy_wh=1000.0,
            forecast_central_energy_wh=1350.0,
            forecast_upper_energy_wh=1700.0,
            forecast_range_status="available",
            forecast_range_source_fields=("pv_estimate10", "pv_estimate90"),
            forecast_range_method_version="solcast-range:v1",
            evidence_type="FORECAST",
            confidence=0.85,
            actual_evidence_ids=(),
            forecast_evidence_ids=("solcast-2",),
            conversion_method_version="solcast:v1",
        ),
    )
    timeline = PVEnergyTimeline(
        timeline_id="pv-timeline-1",
        run_id=bootstrap.run_id,
        snapshot_id=bootstrap.snapshot_id,
        intervals=intervals,
    )
    run = CanonicalPipeline().run(
        planning_input=replace(
            bootstrap,
            pv_energy_timeline=timeline,
        )
    )

    view = build_web_view(run, project(run))

    assert view["schema_version"] == 1
    assert view["observer_only"] is True
    assert view["picot_version"] == run.planning_input.picot_version
    assert view["run_id"] == run.planning_input.run_id
    assert view["snapshot_id"] == run.planning_input.snapshot_id
    assert view["captured_at"] == "2026-08-14T10:00:00+00:00"

    pipeline = view["pipeline"]
    assert len(pipeline) == 9
    assert [item["stage"] for item in pipeline] == list(range(1, 10))
    assert pipeline[0]["entity_id"] == (
        "sensor.picot_v2_pipeline_01_planning_input"
    )
    assert pipeline[0]["state"] == "ready"
    assert pipeline[0]["attributes"]["pv_energy_total_wh"] == 2550.0

    assert view["pv_energy_timeline"] == {
        "available": True,
        "timeline_id": "pv-timeline-1",
        "run_id": run.planning_input.run_id,
        "snapshot_id": run.planning_input.snapshot_id,
        "interval_count": 2,
        "total_wh": 2550.0,
        "starts_at": "2026-08-14T10:30:00+00:00",
        "ends_at": "2026-08-14T11:30:00+00:00",
        "intervals": [
            {
                "interval_id": "pv-interval-1",
                "starts_at": "2026-08-14T10:30:00+00:00",
                "ends_at": "2026-08-14T11:00:00+00:00",
                "pv_energy_wh": 1200.0,
                "forecast_lower_energy_wh": 900.0,
                "forecast_central_energy_wh": 1200.0,
                "forecast_upper_energy_wh": 1500.0,
                "forecast_range_status": "available",
                "evidence_type": "FORECAST",
                "confidence": 0.90,
                "actual_evidence_ids": [],
                "forecast_evidence_ids": ["solcast-1"],
                "conversion_method_version": "solcast:v1",
            },
            {
                "interval_id": "pv-interval-2",
                "starts_at": "2026-08-14T11:00:00+00:00",
                "ends_at": "2026-08-14T11:30:00+00:00",
                "pv_energy_wh": 1350.0,
                "forecast_lower_energy_wh": 1000.0,
                "forecast_central_energy_wh": 1350.0,
                "forecast_upper_energy_wh": 1700.0,
                "forecast_range_status": "available",
                "evidence_type": "FORECAST",
                "confidence": 0.85,
                "actual_evidence_ids": [],
                "forecast_evidence_ids": ["solcast-2"],
                "conversion_method_version": "solcast:v1",
            },
        ],
    }
    assert json.loads(json.dumps(view)) == view


def test_web_view_serializes_readable_household_load_forecast() -> None:
    captured_at = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
    bootstrap = CanonicalPipeline().run(
        captured_at=captured_at
    ).planning_input
    intervals = (
        HouseholdLoadForecastInterval(
            interval_id="household-load-interval-1",
            starts_at=captured_at,
            ends_at=captured_at + timedelta(minutes=15),
            expected_energy_wh=125.0,
            confidence=0.0,
            source_reference="fallback:configured-power",
            method_version="constant-power-conservative-fallback:v1",
        ),
        HouseholdLoadForecastInterval(
            interval_id="household-load-interval-2",
            starts_at=captured_at + timedelta(minutes=15),
            ends_at=captured_at + timedelta(minutes=30),
            expected_energy_wh=150.0,
            confidence=0.0,
            source_reference="fallback:configured-power",
            method_version="constant-power-conservative-fallback:v1",
        ),
    )
    forecast = HouseholdLoadForecast(
        forecast_id="household-load-forecast-1",
        run_id=bootstrap.run_id,
        snapshot_id=bootstrap.snapshot_id,
        intervals=intervals,
        fallback_active=True,
        fallback_reason="insufficient_history",
    )
    run = CanonicalPipeline().run(
        planning_input=replace(
            bootstrap,
            horizon_end=captured_at + timedelta(hours=36),
            household_load_forecast=forecast,
        )
    )

    view = build_web_view(run, project(run))

    assert view["household_load_forecast"] == {
        "available": True,
        "forecast_id": "household-load-forecast-1",
        "run_id": run.planning_input.run_id,
        "snapshot_id": run.planning_input.snapshot_id,
        "interval_count": 2,
        "total_wh": 275.0,
        "average_confidence": 0.0,
        "starts_at": "2026-08-14T10:00:00+00:00",
        "ends_at": "2026-08-14T10:30:00+00:00",
        "fallback_active": True,
        "fallback_reason": "insufficient_history",
        "intervals": [
            {
                "interval_id": "household-load-interval-1",
                "starts_at": "2026-08-14T10:00:00+00:00",
                "ends_at": "2026-08-14T10:15:00+00:00",
                "expected_energy_wh": 125.0,
                "confidence": 0.0,
                "source_reference": "fallback:configured-power",
                "method_version": (
                    "constant-power-conservative-fallback:v1"
                ),
            },
            {
                "interval_id": "household-load-interval-2",
                "starts_at": "2026-08-14T10:15:00+00:00",
                "ends_at": "2026-08-14T10:30:00+00:00",
                "expected_energy_wh": 150.0,
                "confidence": 0.0,
                "source_reference": "fallback:configured-power",
                "method_version": (
                    "constant-power-conservative-fallback:v1"
                ),
            },
        ],
    }


def test_web_view_represents_missing_household_load_forecast() -> None:
    run = CanonicalPipeline().run(
        captured_at=datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
    )

    view = build_web_view(run, project(run))

    assert view["household_load_forecast"] == {
        "available": False,
        "forecast_id": None,
        "run_id": run.planning_input.run_id,
        "snapshot_id": run.planning_input.snapshot_id,
        "interval_count": 0,
        "total_wh": 0,
        "average_confidence": 0.0,
        "starts_at": None,
        "ends_at": None,
        "fallback_active": False,
        "fallback_reason": None,
        "intervals": [],
    }


def test_dashboard_contains_readable_household_load_forecast_panel() -> None:
    assert "Verwacht huishoudverbruik" in DASHBOARD_HTML
    assert 'id="household-load-forecast"' in DASHBOARD_HTML
    assert "renderHouseholdLoadForecast" in DASHBOARD_HTML
    assert "view.household_load_forecast" in DASHBOARD_HTML


def test_dashboard_contains_passive_financial_result_tab() -> None:
    assert 'data-tab="financial"' in DASHBOARD_HTML
    assert 'id="tab-financial"' in DASHBOARD_HTML
    assert 'id="financial-results"' in DASHBOARD_HTML
    assert "renderFinancialResults(view.financial_results ?? {})" in DASHBOARD_HTML
    assert "Netto extra PicoT-resultaat" in DASHBOARD_HTML
    assert "Terugverdienen batterij" in DASHBOARD_HTML
    assert "Herkomst huishoudelijke energie vandaag" in DASHBOARD_HTML
    assert "renderHouseholdEnergySources" in DASHBOARD_HTML
    assert "formatCurrency" in DASHBOARD_HTML
    assert "Bruto batterijvoordeel − slijtage = netto batterijvoordeel" in DASHBOARD_HTML


def test_dashboard_uses_only_canonical_plan_and_evaluation_evidence() -> None:
    assert "MEP-commitment" not in DASHBOARD_HTML
    assert "view.market_daily_planner" not in DASHBOARD_HTML
    assert "view.independent_daily_observer" not in DASHBOARD_HTML
    assert "planner_comparison_history" not in DASHBOARD_HTML


def test_dashboard_contains_canonical_pv_forecast_actual_history_chart() -> None:
    assert 'id="pv-forecast-actual-chart"' in DASHBOARD_HTML
    assert "renderPvForecastActualChart" in DASHBOARD_HTML
    assert "planningInput?.attributes?.pv_interval_deviations" in DASHBOARD_HTML
    assert 'view.pv_energy_timeline ?? { intervals: [] }' in DASHBOARD_HTML
    assert 'view.power_history ?? { pv_actual_display_points: [] }' in DASHBOARD_HTML
    assert "Solcast lower (P10)" in DASHBOARD_HTML
    assert "Solcast verwacht (centraal)" in DASHBOARD_HTML
    assert "Solcast upper (P90)" in DASHBOARD_HTML
    assert "fullEnd.setDate(fullEnd.getDate() + 2)" in DASHBOARD_HTML
    assert "Solcast verwacht" in DASHBOARD_HTML
    assert "GoodWe werkelijk" in DASHBOARD_HTML
    assert "centralEnergyWh / durationHours" in DASHBOARD_HTML
    assert "pvForecastZoomWindow" in DASHBOARD_HTML
    assert "pvForecastInteractionMode" in DASHBOARD_HTML
    assert 'class: "forecast-range"' in DASHBOARD_HTML
    assert 'class: "forecast-line"' in DASHBOARD_HTML
    assert 'class: "actual-line"' in DASHBOARD_HTML
    assert "Nog geen Solcast- of GoodWe-vermogensdata." in DASHBOARD_HTML


def test_incident_history_refresh_preserves_open_details() -> None:
    assert "planningIncidentHistorySignature" in DASHBOARD_HTML
    assert "signature === planningIncidentHistorySignature" in DASHBOARD_HTML
    assert 'container.querySelectorAll("details[open]")' in DASHBOARD_HTML
    assert "details.dataset.incidentKey = incidentKey" in DASHBOARD_HTML
    assert "details.open = openIncidentKeys.has(incidentKey)" in DASHBOARD_HTML


def test_web_view_serializes_canonical_power_history() -> None:
    captured_at = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)
    run = CanonicalPipeline().run(captured_at=captured_at)
    history = PowerHistorySnapshot(
        starts_at=captured_at.replace(hour=0),
        ends_at=captured_at,
        status="available",
        error=None,
        series=(
            PowerHistorySeries(
                series_id="pv",
                role="pv_generation",
                source_entity_id="sensor.pv",
                transform="identity",
                points=(
                    PowerHistoryPoint(
                        sampled_at=captured_at,
                        power_w=1234.0,
                        evidence_id="evidence-pv-1",
                    ),
                ),
            ),
        ),
    )

    view = build_web_view(run, project(run), power_history=history)

    assert view["power_history"] == {
        "available": True,
        "status": "available",
        "error": None,
        "starts_at": "2026-08-17T00:00:00+00:00",
        "ends_at": "2026-08-17T10:00:00+00:00",
        "method_version": "home-assistant-power-history:v1",
        "display_aggregation": "five_minute_average",
        "display_interval_seconds": 300,
        "display_curve": "linear_between_bucket_averages",
        "pv_actual_display_interval_seconds": 120,
        "pv_actual_display_points": [],
        "series": [
            {
                "series_id": "pv",
                "role": "pv_generation",
                "source_entity_id": "sensor.pv",
                "transform": "identity",
                "history_semantics": "state_hold",
                "display_method": "time_weighted_average",
                "display_points": [],
                "points": [
                    {
                        "sampled_at": "2026-08-17T10:00:00+00:00",
                        "power_w": 1234.0,
                        "evidence_id": "evidence-pv-1",
                    }
                ],
            }
        ],
    }


def test_power_history_display_time_weights_state_hold_transitions() -> None:
    starts_at = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)
    series = PowerHistorySeries(
        series_id="battery",
        role="battery_charge",
        source_entity_id="sensor.battery",
        transform="identity",
        history_semantics="state_hold",
        points=(
            PowerHistoryPoint(
                sampled_at=starts_at,
                power_w=0.0,
                evidence_id="battery-0",
            ),
            PowerHistoryPoint(
                sampled_at=starts_at + timedelta(minutes=2),
                power_w=100.0,
                evidence_id="battery-100",
            ),
        ),
    )

    assert _power_history_display_points(
        series,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=5),
    ) == [
        {
            "sampled_at": "2026-08-17T10:02:30+00:00",
            "power_w": 60.0,
            "coverage_ratio": 1.0,
            "derived_from_evidence_ids": ["battery-0", "battery-100"],
        }
    ]


def test_power_history_display_averages_samples_without_filling_gaps() -> None:
    starts_at = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)
    series = PowerHistorySeries(
        series_id="household",
        role="household_load",
        source_entity_id="sensor.household",
        transform="identity",
        history_semantics="sampled_linear",
        points=(
            PowerHistoryPoint(
                sampled_at=starts_at + timedelta(minutes=1),
                power_w=20.0,
                evidence_id="household-20",
            ),
            PowerHistoryPoint(
                sampled_at=starts_at + timedelta(minutes=4),
                power_w=40.0,
                evidence_id="household-40",
            ),
        ),
    )

    assert _power_history_display_points(
        series,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=10),
    ) == [
        {
            "sampled_at": "2026-08-17T10:02:30+00:00",
            "power_w": 30.0,
            "coverage_ratio": 1.0,
            "derived_from_evidence_ids": ["household-20", "household-40"],
        }
    ]


def test_self_consumption_history_subtracts_export_from_pv() -> None:
    starts_at = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)

    def series(role: str, power_w: float) -> PowerHistorySeries:
        return PowerHistorySeries(
            series_id=role,
            role=role,
            source_entity_id=f"sensor.{role}",
            transform="identity",
            points=(PowerHistoryPoint(
                sampled_at=starts_at,
                power_w=power_w,
                evidence_id=f"evidence-{role}",
            ),),
        )

    view = _self_consumption_history_view(PowerHistorySnapshot(
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=10),
        status="available",
        error=None,
        series=(
            series("pv_generation", 1000.0),
            series("grid_export", 300.0),
            series("grid_import", 0.0),
        ),
    ))

    assert view["available"] is True
    assert view["display_interval_seconds"] == 600
    assert view["definition"] == (
        "clamp(pv_generation_w-grid_export_w,0,pv_generation_w)"
    )
    result_series = view["series"]
    assert isinstance(result_series, list)
    local_pv = next(
        item for item in result_series if item["role"] == "local_pv_use"
    )
    assert local_pv["points"] == [{
        "sampled_at": "2026-08-17T10:05:00+00:00",
        "power_w": 700.0,
        "coverage_ratio": 1.0,
        "derived_from_evidence_ids": [
            "evidence-pv_generation",
            "evidence-grid_export",
        ],
    }]


def test_dashboard_contains_self_consumption_history_chart() -> None:
    assert 'id="self-consumption-history-chart"' in DASHBOARD_HTML
    assert "renderSelfConsumptionHistory" in DASHBOARD_HTML
    assert "Zelfverbruik ten opzichte van PV" in DASHBOARD_HTML
    assert 'local_pv_use: "Lokaal gebruikte PV"' in DASHBOARD_HTML
    assert 'grid_import: "Netimport"' in DASHBOARD_HTML
    assert 'stroke: "#ffb300"' in DASHBOARD_HTML


def test_dashboard_contains_canonical_power_history_chart() -> None:
    assert 'id="power-history-chart"' in DASHBOARD_HTML
    assert "renderPowerHistory" in DASHBOARD_HTML
    assert "view.power_history" in DASHBOARD_HTML
    assert 'pv_generation: "PV"' in DASHBOARD_HTML
    assert 'household_load: "Huisverbruik"' in DASHBOARD_HTML
    assert 'grid_import: "Netimport"' in DASHBOARD_HTML
    assert 'grid_export: "Netexport"' in DASHBOARD_HTML


def test_power_history_uses_readable_selectable_day_chart() -> None:
    assert (
        '["pv_generation", "battery_charge", "grid_export"].includes(role)'
        in DASHBOARD_HTML
    )
    assert "stroke-width: 1.2;" in DASHBOARD_HTML
    assert "stroke-linecap: round;" in DASHBOARD_HTML
    assert "stroke-linejoin: round;" in DASHBOARD_HTML
    assert "POWER_HISTORY_SELECTION_KEY" in DASHBOARD_HTML
    assert "picot-power-history-selection" in DASHBOARD_HTML
    assert 'showAll.textContent = "Alles tonen";' in DASHBOARD_HTML
    assert "dayEnd.setDate(dayEnd.getDate() + 1);" in DASHBOARD_HTML
    assert "rawMinimum" in DASHBOARD_HTML
    assert "rawMaximum" in DASHBOARD_HTML
    assert "const padding = span * 0.05;" in DASHBOARD_HTML
    assert "const hasRange = rawMinimum < 0 || rawMaximum > 0;" in DASHBOARD_HTML
    assert "const gridValues = Array.from(new Set([" in DASHBOARD_HTML
    assert "class: value === 0" in DASHBOARD_HTML
    assert "const sourcePoints = [...item.display_points]" in DASHBOARD_HTML
    assert "path += ` L ${point.x} ${point.y}`;" in DASHBOARD_HTML
    assert 'class: `power-flow-area ${item.role}`' in DASHBOARD_HTML
    assert "powerHistoryZoomWindow" in DASHBOARD_HTML
    assert '["+", "Inzoomen"' in DASHBOARD_HTML
    assert '["−", "Uitzoomen"' in DASHBOARD_HTML
    assert 'class: `power-zoom-hitbox ${powerHistoryInteractionMode}`' in DASHBOARD_HTML
    assert 'hitbox.addEventListener("pointerdown"' in DASHBOARD_HTML
    assert 'hitbox.addEventListener("pointerup"' in DASHBOARD_HTML
    assert "powerHistoryInteractionMode" in DASHBOARD_HTML
    assert '["pan", "✋", "Versleep het ingezoomde tijdvak"]' in DASHBOARD_HTML
    assert 'powerHistoryInteractionMode === "pan"' in DASHBOARD_HTML


def test_dashboard_preserves_open_quarter_details_during_refresh() -> None:
    assert (
        'container.querySelector("details")?.open ?? false'
        in DASHBOARD_HTML
    )
    assert "details.open = quarterDetailsOpen" in DASHBOARD_HTML


def test_web_view_exposes_prices_and_detected_windows_for_48_hour_chart() -> None:
    captured_at = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
    bootstrap = CanonicalPipeline().run(
        captured_at=captured_at
    ).planning_input
    price_points = (
        PriceForecastPoint(
            point_id="price-low",
            starts_at=captured_at,
            ends_at=captured_at + timedelta(minutes=15),
            value_eur_per_kwh=-0.02,
            confidence=1.0,
            evidence_id="nordpool-day-1",
        ),
        PriceForecastPoint(
            point_id="price-high",
            starts_at=captured_at + timedelta(minutes=15),
            ends_at=captured_at + timedelta(minutes=30),
            value_eur_per_kwh=0.38,
            confidence=1.0,
            evidence_id="nordpool-day-1",
        ),
        PriceForecastPoint(
            point_id="price-outside-planning-horizon",
            starts_at=captured_at + timedelta(hours=47),
            ends_at=captured_at + timedelta(
                hours=47,
                minutes=15,
            ),
            value_eur_per_kwh=0.21,
            confidence=1.0,
            evidence_id="nordpool-day-2",
        ),
    )
    run = CanonicalPipeline().run(
        planning_input=replace(
            bootstrap,
            horizon_end=captured_at + timedelta(hours=36),
            price_points=price_points,
        ),
        price_opportunity_config=PriceOpportunityConfig(
            low_price_margin_eur_per_kwh=0.0,
            high_price_margin_eur_per_kwh=0.0,
            config_version="price-chart-test:v1",
        ),
    )

    view = build_web_view(run, project(run))

    price_timeline = view["price_timeline"]
    assert price_timeline["display_hours"] == 48
    assert price_timeline["market_timezone"] == "Europe/Amsterdam"
    assert price_timeline["planning_horizon_ends_at"] == (
        "2026-08-15T22:00:00+00:00"
    )
    assert [point["point_id"] for point in price_timeline["points"]] == [
        "price-low",
        "price-high",
        "price-outside-planning-horizon",
    ]
    assert {
        opportunity["kind"]
        for opportunity in price_timeline["opportunities"]
    } >= {
        "LOWEST_PRICE_WINDOW",
        "HIGH_EXPORT_VALUE_WINDOW",
    }


def test_web_view_shows_elapsed_today_without_adding_it_to_canonical_input() -> None:
    captured_at = datetime(2026, 8, 14, 20, 0, tzinfo=UTC)
    bootstrap = CanonicalPipeline().run(
        captured_at=captured_at
    ).planning_input
    elapsed = PriceForecastPoint(
        point_id="price-elapsed-today",
        starts_at=captured_at - timedelta(hours=18),
        ends_at=captured_at - timedelta(hours=17),
        value_eur_per_kwh=0.31,
        confidence=1.0,
        evidence_id="nordpool-today",
    )
    future = PriceForecastPoint(
        point_id="price-future",
        starts_at=captured_at + timedelta(hours=1),
        ends_at=captured_at + timedelta(hours=2),
        value_eur_per_kwh=0.18,
        confidence=1.0,
        evidence_id="nordpool-today",
    )
    run = CanonicalPipeline().run(
        planning_input=replace(
            bootstrap,
            horizon_end=captured_at + timedelta(hours=36),
            price_points=(future,),
        )
    )

    view = build_web_view(
        run,
        project(run),
        display_price_points=(elapsed, future),
    )

    assert run.planning_input.price_points == (future,)
    price_timeline = view["price_timeline"]
    assert price_timeline["display_starts_at"] == (
        "2026-08-14T00:00:00+02:00"
    )
    assert price_timeline["display_ends_at"] == (
        "2026-08-16T00:00:00+02:00"
    )
    assert [
        point["point_id"]
        for point in price_timeline["points"]
    ] == ["price-elapsed-today", "price-future"]


def test_dashboard_contains_48_hour_price_window_chart() -> None:
    assert "Prijsverloop vandaag en morgen" in DASHBOARD_HTML
    assert 'id="price-timeline"' in DASHBOARD_HTML
    assert "renderPriceTimeline" in DASHBOARD_HTML
    assert "display_starts_at" in DASHBOARD_HTML
    assert "display_ends_at" in DASHBOARD_HTML
    assert ".price-bar.past" in DASHBOARD_HTML
    assert "now-line" in DASHBOARD_HTML
    assert "const nowMs = Date.now();" in DASHBOARD_HTML
    assert "pointEnd <= nowMs" in DASHBOARD_HTML
    assert "Nog niet gepubliceerd" in DASHBOARD_HTML


def test_price_chart_only_colors_current_planner_windows() -> None:
    assert ".price-bar.low" not in DASHBOARD_HTML
    assert ".price-bar.high" not in DASHBOARD_HTML
    assert '["low", "Laagste-prijsvenster"]' not in DASHBOARD_HTML
    assert '["high", "Hoogste-teruglevervenster"]' not in DASHBOARD_HTML
    assert ".planner-window.canonical-charge" in DASHBOARD_HTML
    assert ".planner-window.canonical-trade" in DASHBOARD_HTML
    assert ".planner-window.daily-plan" not in DASHBOARD_HTML
    assert ".price-bar.mep-charge" not in DASHBOARD_HTML
    assert ".price-bar.mep-export" not in DASHBOARD_HTML


def test_dashboard_shows_plan_calculation_time_and_soc() -> None:
    assert '["Plan berekend", formatTimestamp(status.captured_at)]' in DASHBOARD_HTML
    assert "SoC bij berekening" in DASHBOARD_HTML


def test_web_view_represents_missing_pv_timeline_without_intervals() -> None:
    run = CanonicalPipeline().run(
        captured_at=datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
    )

    view = build_web_view(run, project(run))

    assert view["pv_energy_timeline"] == {
        "available": False,
        "timeline_id": None,
        "run_id": run.planning_input.run_id,
        "snapshot_id": run.planning_input.snapshot_id,
        "interval_count": 0,
        "total_wh": 0,
        "starts_at": None,
        "ends_at": None,
        "intervals": [],
    }


def test_web_view_store_atomically_replaces_latest_serialized_view() -> None:
    store = WebViewStore()
    first: dict[str, object] = {
        "run_id": "run-1",
        "pipeline": [{"stage": 1, "state": "ready"}],
    }
    second: dict[str, object] = {
        "run_id": "run-2",
        "pipeline": [{"stage": 1, "state": "updated"}],
    }

    assert store.latest_json() is None

    store.publish(first)
    first["run_id"] = "mutated-after-publish"
    first_json = store.latest_json()

    assert first_json is not None
    assert json.loads(first_json) == {
        "run_id": "run-1",
        "pipeline": [{"stage": 1, "state": "ready"}],
    }

    store.publish(second)
    second_json = store.latest_json()

    assert second_json is not None
    assert json.loads(second_json) == {
        "run_id": "run-2",
        "pipeline": [{"stage": 1, "state": "updated"}],
    }


def test_web_view_store_refreshes_history_without_replacing_planner_run() -> None:
    store = WebViewStore()
    starts_at = datetime(2026, 8, 22, 0, 0, tzinfo=UTC)
    ends_at = starts_at + timedelta(hours=3)
    store.publish({
        "run_id": "run-02-04",
        "power_history": {"ends_at": starts_at.isoformat()},
        "self_consumption_history": {"ends_at": starts_at.isoformat()},
    })
    history = PowerHistorySnapshot(
        starts_at=starts_at,
        ends_at=ends_at,
        status="available",
        error=None,
        series=(PowerHistorySeries(
            series_id="pv",
            role="pv_generation",
            source_entity_id="sensor.pv",
            transform="identity",
            points=(PowerHistoryPoint(
                sampled_at=ends_at,
                power_w=250.0,
                evidence_id="evidence-pv-latest",
            ),),
        ),),
    )

    store.publish_power_history(history)

    latest_json = store.latest_json()
    assert latest_json is not None
    latest = json.loads(latest_json)
    assert latest["run_id"] == "run-02-04"
    assert latest["power_history"]["ends_at"] == ends_at.isoformat()


def test_dashboard_exposes_canonical_mep_execution_plan() -> None:
    assert "Energieplan batterij" in DASHBOARD_HTML
    assert 'id="storage-energy-source-needs"' in DASHBOARD_HTML
    assert "renderBatteryEnergyPlan" in DASHBOARD_HTML
    assert "executionPlanDayLabel" in DASHBOARD_HTML
    assert "MEP-uitvoeringsplan" in DASHBOARD_HTML
    assert "Handmatige instelling actief" in DASHBOARD_HTML
    assert "storage_source_needs" not in DASHBOARD_HTML


def test_price_bars_use_existing_energy_palette_for_mep_actions() -> None:
    assert ".price-bar.canonical-charge" in DASHBOARD_HTML
    assert ".price-bar.canonical-trade" in DASHBOARD_HTML
    assert ".price-swatch.canonical-nom { background: #35a862; }" in (
        DASHBOARD_HTML
    )
    assert ".price-swatch.canonical-charge { background: #df5c57; }" in (
        DASHBOARD_HTML
    )
    assert ".price-swatch.canonical-trade { background: #aab2bd; }" in (
        DASHBOARD_HTML
    )
    assert '["canonical-nom", "NOM / PV laden"]' in DASHBOARD_HTML
    assert '["canonical-charge", "Net import / snel laden"]' in DASHBOARD_HTML
    assert '["canonical-trade", "MEP handel / terugleveren"]' in DASHBOARD_HTML
    assert 'charge_at_power: "canonical-charge"' in DASHBOARD_HTML
    assert 'discharge_at_power: "canonical-trade"' in DASHBOARD_HTML
    assert ".price-swatch.canonical-support { background: #3994e6; }" in (
        DASHBOARD_HTML
    )
    assert ".price-chart .soc-line.canonical-support" in DASHBOARD_HTML
    assert "stroke: #3994e6;" in DASHBOARD_HTML


def test_price_chart_has_room_for_soc_and_one_plan_lane() -> None:
    assert "min-width: 1000px;" in DASHBOARD_HTML
    assert "const width = 1280;" in DASHBOARD_HTML
    assert "const height = 430;" in DASHBOARD_HTML
    assert "bottom: 76" in DASHBOARD_HTML
    assert "y: height - margin.bottom + 14" in DASHBOARD_HTML
    assert "(plotHeight - 20)" in DASHBOARD_HTML


def test_dashboard_preserves_interaction_state_during_refresh() -> None:
    # Polling may continue, but rendering must wait while text is selected.
    assert "pendingView" in DASHBOARD_HTML
    assert "shouldDeferRenderForSelection" in DASHBOARD_HTML

    # Re-rendering must restore disclosure and scroll state.
    assert "captureDashboardState" in DASHBOARD_HTML
    assert "restoreDashboardState" in DASHBOARD_HTML
    assert "openTechnicalDetails" in DASHBOARD_HTML
    assert "scrollPositions" in DASHBOARD_HTML

def test_dashboard_uses_dutch_adaptive_power_and_energy_formatting() -> None:
    assert "function formatDutchNumber" in DASHBOARD_HTML
    assert 'minimumFractionDigits: 2' in DASHBOARD_HTML
    assert 'maximumFractionDigits: 2' in DASHBOARD_HTML
    assert 'formatMeasurement(value, unit)' in DASHBOARD_HTML
    assert 'formatDutchNumber(numeric / 1000) + " kW"' in DASHBOARD_HTML
    assert 'formatDutchNumber(numeric) + " W"' in DASHBOARD_HTML
    assert 'formatDutchNumber(numeric / 1000) + " kWh"' in DASHBOARD_HTML
    assert 'formatDutchNumber(numeric) + " Wh"' in DASHBOARD_HTML


def test_dashboard_preserves_active_tab_during_realtime_updates() -> None:
    assert "initializeTabs" in DASHBOARD_HTML
    assert 'document.querySelector(\'.tab-button[aria-selected="true"]\')' in (
        DASHBOARD_HTML
    )
    assert 'document.querySelector(".tab-button[aria-selected="true"]")' not in (
        DASHBOARD_HTML
    )
    assert "activateTab" in DASHBOARD_HTML
    assert "ACTIVE_TAB_KEY" in DASHBOARD_HTML
    assert "activeTab:" in DASHBOARD_HTML
    assert 'activateTab(state.activeTab ?? "overview")' in DASHBOARD_HTML

def test_web_view_store_overlays_fast_grid_power_without_planner_run() -> None:
    store = WebViewStore()
    base_view: dict[str, object] = {
        "run_id": "run-planner-1",
        "pipeline": [
            {
                "stage": 1,
                "attributes": {
                    "sources": [
                        {
                            "category": "p1",
                            "semantic_role": "grid_power",
                            "raw_state": "100",
                            "raw_unit": "W",
                        }
                    ]
                },
            }
        ],
    }
    store.publish(base_view)
    store.publish_fast_grid_power_source(
        {
            "category": "p1",
            "semantic_role": "grid_power",
            "entity_id": "sensor.ct_shelly_pro_3em_api",
            "raw_state": "8.345",
            "raw_unit": "W",
            "observed_at": "2026-08-17T07:00:01+00:00",
            "availability": "available",
        }
    )

    latest_json = store.latest_json()
    assert latest_json is not None
    latest = json.loads(latest_json)
    assert latest["run_id"] == "run-planner-1"
    assert latest["pipeline"][0]["attributes"]["sources"][0][
        "raw_state"
    ] == "8.345"

    store.publish(base_view)
    republished_json = store.latest_json()
    assert republished_json is not None
    republished = json.loads(republished_json)
    assert republished["pipeline"][0]["attributes"]["sources"][0][
        "raw_state"
    ] == "8.345"


def test_web_view_store_overlays_fresh_soc_without_replacing_plan() -> None:
    store = WebViewStore()
    store.publish({
        "run_id": "run-committed-plan",
        "pipeline": [{
            "stage": 1,
            "attributes": {"sources": [], "source_count": 0},
        }],
    })

    store.publish_planning_input_sources([{
        "semantic_role": "storage_soc",
        "raw_state": "97",
        "availability": "available",
    }])

    latest_json = store.latest_json()
    assert latest_json is not None
    latest = json.loads(latest_json)
    assert latest["run_id"] == "run-committed-plan"
    attributes = latest["pipeline"][0]["attributes"]
    assert attributes["sources"][0]["raw_state"] == "97"
    assert attributes["source_count"] == 1
    assert attributes["source_available_count"] == 1

def test_dashboard_exposes_exact_chosen_execution_plan_facts() -> None:
    assert "Gekozen uitvoeringsplan" in DASHBOARD_HTML
    assert 'const chosenPlan = status.chosen_plan ?? {};' in DASHBOARD_HTML
    assert '"Plan-ID"' in DASHBOARD_HTML
    assert '"Planrevisie"' in DASHBOARD_HTML
    assert '"Laadvenster vanaf"' in DASHBOARD_HTML
    assert '"Totale doelenergie"' in DASHBOARD_HTML
    assert '"Batterijenergie bij berekening"' in DASHBOARD_HTML
    assert '"Verwacht accuverbruik tot laadstart"' in DASHBOARD_HTML
    assert '"Verwachte energie bij laadstart"' in DASHBOARD_HTML
    assert '"Benodigde toevoeging bij laadstart"' in DASHBOARD_HTML
    assert '"Gebruikte PV-forecastbasis"' in DASHBOARD_HTML
    assert '"Energie einde laadvenster"' in DASHBOARD_HTML
    assert '"Energie bij deadline"' in DASHBOARD_HTML
    assert '"Bijdrage PV"' in DASHBOARD_HTML
    assert '"Bijdrage net"' in DASHBOARD_HTML
    assert '"Planconfidence"' in DASHBOARD_HTML
    assert '"Slechtste financiële uitkomst"' in DASHBOARD_HTML
    assert '"Minimale energie einde horizon"' in DASHBOARD_HTML
    assert 'availablePlanningRows([' in DASHBOARD_HTML
    assert 'chosenPlan.execution_segments' in DASHBOARD_HTML
    assert '"Batterijmodus"' in DASHBOARD_HTML
    assert '"Laadbron"' in DASHBOARD_HTML


def test_web_view_exposes_chosen_plan_contract_even_without_a_winner() -> None:
    run = CanonicalPipeline().run(
        captured_at=datetime(2026, 8, 17, 10, 0, tzinfo=UTC)
    )

    chosen_plan = build_web_view(run, project(run))["planning_status"][
        "chosen_plan"
    ]

    assert set(chosen_plan) == {
        "plan_id",
        "plan_revision",
        "execution_scope_id",
        "valid_from",
        "valid_until",
        "source_policy",
        "average_charge_window_price_eur_per_kwh",
        "worst_case_financial_result_eur",
        "minimum_storage_energy_at_horizon_end_wh",
        "reserve_respected_across_scenarios",
        "target_held_across_scenarios",
        "candidate_id",
        "energy_path_id",
        "family",
        "decisive_step",
        "reason",
        "charge_window_starts_at",
        "charge_window_ends_at",
        "required_energy_wh",
        "initial_storage_energy_wh",
            "energy_to_target_wh",
            "storage_energy_at_window_start_wh",
            "projected_storage_use_before_window_wh",
            "required_storage_addition_wh",
            "pv_forecast_basis",
            "charge_target_satisfied",
            "reserve_satisfied",
            "reserve_energy_required_wh",
        "storage_energy_at_window_end_wh",
        "storage_energy_at_requirement_wh",
        "pv_contribution_wh",
        "grid_contribution_wh",
        "conversion_losses_wh",
        "requirement_satisfied",
        "recoverability",
        "confidence",
        "requirement_confidence",
        "confidence_assessment",
        "execution_segments",
    }
    assert isinstance(chosen_plan["execution_segments"], list)


def test_dashboard_does_not_render_missing_confidence_as_zero_percent() -> None:
    assert "if (value === null || value === undefined) return \"—\";" in (
        DASHBOARD_HTML
    )


def test_dashboard_compares_chosen_and_rejected_candidate_facts() -> None:
    assert '"Kandidaat", "Planfamilie", "Gekozen", "Venster vanaf", "Venster tot"' in (
        DASHBOARD_HTML
    )
    assert '"Energie einde venster", "Energie bij deadline", "Doel gehaald"' in (
        DASHBOARD_HTML
    )
    assert '"PV", "Net", "Herstelbaarheid", "Confidence"' in DASHBOARD_HTML
    assert "alternative.candidate_id" in DASHBOARD_HTML
    assert "alternative.charge_window_starts_at" in DASHBOARD_HTML
    assert "alternative.charge_window_ends_at" in DASHBOARD_HTML
    assert "alternative.storage_energy_at_window_end_wh" in DASHBOARD_HTML
    assert "alternative.storage_energy_at_requirement_wh" in DASHBOARD_HTML
    assert "alternative.recoverability" in DASHBOARD_HTML
