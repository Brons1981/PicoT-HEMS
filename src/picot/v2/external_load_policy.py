"""One optional Energy Devices snapshot boundary; no vendor mode selection."""

from dataclasses import replace
from datetime import datetime, timedelta
from hashlib import sha256
from math import isfinite
from typing import cast

from picot.domain.external_load_policy import ExternalLoadPolicy
from picot.v2.contracts import HouseholdLoadForecast

METHOD = "measured-external-load-support-policy:v1"
SESSION_METHOD = "energy-device-session-demand:v1"


def read_external_load_policy(
    payload: dict[str, object] | None,
    *,
    captured_at: datetime,
    execution_scope_id: str,
) -> ExternalLoadPolicy | None:
    if not payload or payload.get("contract") != METHOD:
        return None
    # A shadow estimate never proves that storage exclusion is actually enabled.
    if payload.get("control_enabled") is not True or payload.get("status") != "ready":
        return None
    try:
        raw = payload["measured_at"]
        if not isinstance(raw, str):
            return None
        when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        power = payload["ev_w"]
        if isinstance(power, bool) or not isinstance(power, (float, int)):
            return None
        if when.tzinfo is None or not 0 <= (captured_at - when).total_seconds() <= 3:
            return None
        if not isfinite(power) or power < 0:
            return None
        source = payload.get("source_id")
        revision = payload.get("revision")
        if not isinstance(source, str) or not isinstance(revision, str):
            return None
        return ExternalLoadPolicy(
            source,
            revision,
            when,
            float(power),
            False,
            execution_scope_id,
            physical_evidence_available=True,
        )
    except (KeyError, ValueError):
        return None


def read_session_demand(
    payload: dict[str, object] | None,
    *,
    captured_at: datetime,
    execution_scope_id: str,
    live_policy: ExternalLoadPolicy | None = None,
) -> ExternalLoadPolicy | None:
    """Admit explicitly confirmed demand independently of regulation authority."""
    if (
        not payload
        or payload.get("contract") != SESSION_METHOD
        or payload.get("source_id") != "energy-devices:ev-session"
    ):
        return None
    try:
        stamp = payload.get("generated_at")
        if not isinstance(stamp, str):
            return None
        generated = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if generated.tzinfo is None or not 0 <= (captured_at - generated).total_seconds() <= 15:
            return None
        session = payload.get("session")
        if not isinstance(session, dict) or session.get("confirmed") is not True:
            return None
        state = session.get("state")
        if state not in {"planned", "active", "interrupted"}:
            return None
        start_raw = session.get("planned_start")
        if not isinstance(start_raw, str):
            return None
        start = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
        remaining = session.get("remaining_energy_wh")
        expected = session.get("expected_power_w")
        duration = session.get("expected_duration_seconds")
        for value in (remaining, expected, duration):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
            ):
                return None
        remaining = cast(float, remaining)
        expected = cast(float, expected)
        duration = cast(float, duration)
        if not 0 <= remaining <= 88320 or not 100 <= expected <= 3680 or not 0 < duration <= 86400:
            return None
        if start.tzinfo is None:
            return None
        start + timedelta(seconds=duration)  # reject an unrepresentable deadline
        actual = session.get("current_power_w")
        physical = 0.0
        physical_available = False
        measured = session.get("last_measured_at")
        if (
            isinstance(actual, (int, float))
            and not isinstance(actual, bool)
            and isfinite(actual)
            and actual >= 0
            and isinstance(measured, str)
        ):
            when = datetime.fromisoformat(measured.replace("Z", "+00:00"))
            if when.tzinfo is not None and 0 <= (captured_at - when).total_seconds() <= 15:
                physical = float(actual)
                physical_available = True
        if not physical_available:
            if session.get("switch_state") == "off":
                physical_available = True  # a confirmed off charger cannot supply the EV…11930 tokens truncated…        lower_power_kw = float(raw_lower_power_kw)
            upper_power_kw = float(raw_upper_power_kw)
            if (
                isfinite(lower_power_kw)
                and isfinite(average_power_kw)
                and isfinite(upper_power_kw)
                and 0.0
                <= lower_power_kw
                <= average_power_kw
                <= upper_power_kw
            ):
                lower_energy_wh = lower_power_kw * 0.5 * 1000.0
                central_energy_wh = average_power_kw * 0.5 * 1000.0
                upper_energy_wh = upper_power_kw * 0.5 * 1000.0
                range_status = "available"
                range_fields = range_source_fields
                range_version = range_method_version

        ends_at = starts_at + timedelta(minutes=30)
        seed = (
            f"{evidence_id}|{starts_at.isoformat()}|"
            f"{ends_at.isoformat()}|{average_power_kw}|"
            f"{method_version}"
        )
        result.append(
            PVEnergyTimelineInterval(
                interval_id=_stable_id(
                    "pv-energy-interval",
                    seed,
                ),
                starts_at=starts_at,
                ends_at=ends_at,
                pv_energy_wh=average_power_kw * 0.5 * 1000.0,
                evidence_type="FORECAST",
                forecast_lower_energy_wh=lower_energy_wh,
                forecast_central_energy_wh=central_energy_wh,
                forecast_upper_energy_wh=upper_energy_wh,
                forecast_range_status=range_status,
                forecast_range_source_fields=range_fields,
                forecast_range_method_version=range_version,
                confidence=confidence,
                actual_evidence_ids=(),
                forecast_evidence_ids=(evidence_id,),
                conversion_method_version=method_version,
            )
        )

    return tuple(
        sorted(
            result,
            key=lambda interval: interval.starts_at,
        )
    )


def _price_points_from_attributes(
    attributes: dict[str, Any],
    *,
    evidence_id: str,
) -> tuple[PriceForecastPoint, ...]:
    raw_points: list[dict[str, Any]] = []
    for key in ("raw_today", "raw_tomorrow"):
        value = attributes.get(key, [])
        if isinstance(value, list):
            raw_points.extend(item for item in value if isinstance(item, dict))

    result: list[PriceForecastPoint] = []
    for item in raw_points:
        starts_at = _parse_datetime(item.get("start"))
        ends_at = _parse_datetime(item.get("end"))
        raw_price = item.get("value", item.get("price"))
        if starts_at is None or ends_at is None or ends_at <= starts_at:
            continue
        if isinstance(raw_price, bool) or not isinstance(raw_price, (int, float)):
            continue
        seed = f"{evidence_id}|{starts_at.isoformat()}|{ends_at.isoformat()}|{float(raw_price)}"
        result.append(
            PriceForecastPoint(
                point_id=_stable_id("price-point", seed),
                starts_at=starts_at,
                ends_at=ends_at,
                value_eur_per_kwh=float(raw_price),
                confidence=1.0,
                evidence_id=evidence_id,
            )
        )
    return tuple(sorted(result, key=lambda point: (point.starts_at, point.ends_at)))


def load_options(options_path: str = "/data/options.json") -> dict[str, Any]:
    path = Path(options_path)
    if not path.exists():
        return {}
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        return {}
    # All consumers (including Recorder recovery and display history) must
    # resolve the same storage identity as live Planning Input. Never migrate
    # only a binding while leaving the runtime's options on an individual unit.
    raw_soc = parsed.get("zendure_soc_entity")
    if isinstance(raw_soc, str):
        entity_id = raw_soc.strip()
        parsed["zendure_soc_entity"] = LEGACY_SOC_ENTITY_MIGRATIONS.get(entity_id, entity_id)
    return parsed


def load_storage_state_config(
    options_path: str = "/data/options.json",
) -> StorageStateConfig | None:
    options = load_options(options_path)
    execution_scope_id = options.get("storage_execution_scope_id")
    capability_id = options.get("storage_capability_id")
    raw_capacity = options.get("storage_usable_capacity_wh")
    raw_minimum_soc_percent = options.get("storage_minimum_soc_percent")
    raw_maximum_soc_percent = options.get(
        "storage_maximum_soc_percent",
        DEFAULT_STORAGE_MAXIMUM_SOC_PERCENT,
    )
    raw_maximum_charge_power_w = options.get(
        "storage_maximum_charge_power_w",
        DEFAULT_STORAGE_MAXIMUM_CHARGE_POWER_W,
    )
    raw_maximum_discharge_power_w = options.get(
        "storage_maximum_discharge_power_w",
        DEFAULT_STORAGE_MAXIMUM_DISCHARGE_POWER_W,
    )

    if (
        not isinstance(execution_scope_id, str)
        or not execution_scope_id.strip()
        or not isinstance(capability_id, str)
        or not capability_id.strip()
        or isinstance(raw_capacity, bool)
        or not isinstance(raw_capacity, (int, float))
    ):
        return None

    usable_capacity_wh = float(raw_capacity)
    if usable_capacity_wh <= 0.0:
        return None

    minimum_soc = None
    if (
        not isinstance(raw_minimum_soc_percent, bool)
        and isinstance(raw_minimum_soc_percent, (int, float))
        and 0.0 <= float(raw_minimum_soc_percent) <= 100.0
    ):
        minimum_soc = float(raw_minimum_soc_percent) / 100.0

    maximum_soc = None
    if (
        not isinstance(raw_maximum_soc_percent, bool)
        and isinstance(raw_maximum_soc_percent, (int, float))
        and 0.0 <= float(raw_maximum_soc_percent) <= 100.0
    ):
        maximum_soc = float(raw_maximum_soc_percent) / 100.0

    maximum_charge_power_w = None
    if (
        not isinstance(raw_maximum_charge_power_w, bool)
        and isinstance(raw_maximum_charge_power_w, (int, float))
        and float(raw_maximum_charge_power_w) > 0.0
    ):
        maximum_charge_power_w = float(raw_maximum_charge_power_w)

    maximum_discharge_power_w = None
    if (
        not isinstance(raw_maximum_discharge_power_w, bool)
        and isinstance(raw_maximum_discharge_power_w, (int, float))
        and float(raw_maximum_discharge_power_w) > 0.0
    ):
        maximum_discharge_power_w = float(raw_maximum_discharge_power_w)

    return StorageStateConfig(
        execution_scope_id=execution_scope_id.strip(),
        capability_id=capability_id.strip(),
        usable_capacity_wh=usable_capacity_wh,
        minimum_soc=minimum_soc,
        maximum_soc=maximum_soc,
        maximum_charge_power_w=maximum_charge_power_w,
        maximum_discharge_power_w=maximum_discharge_power_w,
    )


def load_bindings(options_path: str = "/data/options.json") -> tuple[SourceBinding, ...]:
    options = load_options(options_path)
    result: list[SourceBinding] = []
    for category, semantic_role, option_key in DEFAULT_BINDINGS:
        raw = options.get(option_key)
        entity_id = raw.strip() if isinstance(raw, str) and raw.strip() else None
        result.append(SourceBinding(category, semantic_role, entity_id))
    return tuple(result)


def load_storage_mode_capability_config(
    options_path: str = "/data/options.json",
) -> StorageModeCapabilityConfig | None:
    options = load_options(options_path)
    values = (
        options.get("zendure_mode_entity"),
        options.get("storage_capability_id"),
        options.get("storage_execution_scope_id"),
    )
    if not all(
        isinstance(value, str) and value.strip()
        for value in values
    ):
        return None
    source_entity_id, capability_id, execution_scope_id = values
    assert isinstance(source_entity_id, str)
    assert isinstance(capability_id, str)
    assert isinstance(execution_scope_id, str)
    return StorageModeCapabilityConfig(
        source_entity_id=source_entity_id.strip(),
        capability_id=capability_id.strip(),
        execution_scope_id=execution_scope_id.strip(),
    )


class HomeAssistantStateReader:
    """Reads each configured HA source exactly once during snapshot assembly."""

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("Supervisor token is required")
        self._token = token

    def read(self, binding: SourceBinding) -> SourceEvidence:
        mapping_version = _stable_id(
            "mapping", f"{binding.category}|{binding.semantic_role}|{binding.entity_id or 'none'}"
        )
        evidence_id = _stable_id(
            "evidence", f"{mapping_version}|{datetime.now(UTC).isoformat()}"
        )
        if binding.entity_id is None:
            return SourceEvidence(
                evidence_id=evidence_id,
                category=binding.category,
                semantic_role=binding.semantic_role,
                entity_id=None,
                raw_state=None,
                raw_unit=None,
                observed_at=None,
                availability="unconfigured",
                mapping_version=mapping_version,
            )

        request = Request(
            f"http://supervisor/core/api/states/{quote(binding.entity_id, safe='.')}",
            headers={"Authorization": f"Bearer {self._token}"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            return SourceEvidence(
                evidence_id=evidence_id,
                category=binding.category,
                semantic_role=binding.semantic_role,
                entity_id=binding.entity_id,
                raw_state=None,
                raw_unit=None,
                observed_at=None,
                availability="unavailable",
                mapping_version=mapping_version,
                error=type(exc).__name__,
            )

        raw_state = str(payload.get("state")) if payload.get("state") is not None else None
        attributes = payload.get("attributes")
        typed_attributes = attributes if isinstance(attributes, dict) else {}
        unit = typed_attributes.get("unit_of_measurement")
        unavailable = raw_state in {"unknown", "unavailable", None}
        price_points: tuple[PriceForecastPoint, ...] = ()
        pv_energy_intervals: tuple[PVEnergyTimelineInterval, ...] = ()
        if binding.category == "nordpool" and not unavailable:
            price_points = _price_points_from_attributes(
                typed_attributes,
                evidence_id=evidence_id,
            )
        if binding.category == "solcast" and not unavailable:
            pv_energy_intervals = _pv_forecast_intervals_from_attributes(
                typed_attributes,
                evidence_id=evidence_id,
            )
        return SourceEvidence(
            evidence_id=evidence_id,
            category=binding.category,
            semantic_role=binding.semantic_role,
            entity_id=binding.entity_id,
            raw_state=raw_state,
            raw_unit=str(unit) if unit is not None else None,
            observed_at=_parse_datetime(payload.get("last_updated")),
            state_read_at=datetime.now(UTC) if not unavailable
            and binding.category == "zendure" and binding.semantic_role in {
                "storage_soc", "storage_power_to_house", "storage_power_from_house",
            } else None,
            availability="unavailable" if unavailable else "available",
            mapping_version=mapping_version,
            last_changed_at=_parse_datetime(payload.get("last_changed")),
            last_updated_at=_parse_datetime(payload.get("last_updated")),
            error=(
                "price_forecast_points_missing"
                if binding.category == "nordpool" and not unavailable and not price_points
                else None
            ),
            price_points=price_points,
            pv_energy_intervals=pv_energy_intervals,
            external_load_payload=(
                typed_attributes
                if binding.semantic_role in {"external_load_policy", "ev_session_demand"}
                and not unavailable else None
            ),
        )


def assemble_planning_input(
    token: str,
    *,
    bindings: tuple[SourceBinding, ...] | None = None,
    storage_state_config: StorageStateConfig | None = None,
    storage_mode_capability_config: StorageModeCapabilityConfig | None = None,
    options_path: str = "/data/options.json",
    captured_at: datetime | None = None,
    household_load_fallback_power_w: float | None = None,
    household_load_fallback_confidence: float = 0.5,
    household_load_observations: tuple[
        HouseholdLoadObservation,
        ...,
    ] = (),
) -> PlanningInputBundle:
    options = load_options(options_path)
    raw_unexpected_reserve_percent = options.get(
        "household_unexpected_reserve_percent", 10.0
    )
    household_unexpected_reserve_fraction = (
        float(raw_unexpected_reserve_percent) / 100.0
        if not isinstance(raw_unexpected_reserve_percent, bool)
        and isinstance(raw_unexpected_reserve_percent, (int, float))
        and 0.0 <= float(raw_unexpected_reserve_percent) <= 100.0
        else 0.10
    )
    started = datetime.now(UTC)
    reader = HomeAssistantStateReader(token)
    selected = bindings if bindings is not None else load_bindings(options_path)
    selected_storage_config = storage_state_config
    selected_mode_config = storage_mode_capability_config
    if bindings is None and selected_storage_config is None:
        selected_storage_config = load_storage_state_config(options_path)
    if bindings is None and selected_mode_config is None:
        selected_mode_config = load_storage_mode_capability_config(options_path)

    evidence = tuple(reader.read(binding) for binding in selected)
    finished = datetime.now(UTC)
    capture = captured_at or finished
    if capture.tzinfo is None or capture.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")
    storage_mode_capability_evidence = (
        HomeAssistantZendureModeCapabilityReader(token).read(
            selected_mode_config,
            captured_at=capture,
        )
        if selected_mode_config is not None
        else None
    )

    household_load_observation, household_load_rejection_reason = (
        _assess_household_load_evidence(
            evidence,
            sampled_at=capture,
        )
    )

    external_load_policy = None
    if (
        options.get("energy_device_policy_enabled", False) is True
        or options.get("energy_device_sessions_enabled", False) is True
    ) and selected_storage_config:
        source = next((e for e in evidence if e.semantic_role == "external_load_policy"), None)
        external_load_policy = read_external_load_policy(
            source.external_load_payload if source else None,
            captured_at=capture, execution_scope_id=selected_storage_config.execution_scope_id,
        )
        if options.get("energy_device_policy_enabled", False) is not True:
            external_load_policy = None
        if options.get("energy_device_sessions_enabled", False) is True:
            session_source = next(
                (e for e in evidence if e.semantic_role == "ev_session_demand"), None
            )
            demand = read_session_demand(
                session_source.external_load_payload if session_source else None,
                captured_at=capture, execution_scope_id=selected_storage_config.execution_scope_id,
                live_policy=external_load_policy,
            )
            if demand is not None:
                external_load_policy = demand
        if external_load_policy is not None and household_load_observation is not None:
            household_load_observation = replace(household_load_observation,
                identified_external_power_w=min(external_load_policy.power_w,
                                                household_load_observation.power_w),
                external_power_observed=external_load_policy.physical_evidence_available)

    evidence_seed = "|".join(
        f"{item.mapping_version}:{item.raw_state}:{item.observed_at}" for item in evidence
    )
    if storage_mode_capability_evidence is not None:
        evidence_seed += (
            "|storage-mode:"
            f"{storage_mode_capability_evidence.current_vendor_mode}:"
            f"{storage_mode_capability_evidence.status}:"
            f"{storage_mode_capability_evidence.usable_vendor_modes}:"
            f"{storage_mode_capability_evidence.excluded_dynamic_vendor_modes}"
        )
    evidence_seed += "|solcast-planning-basis:" + str(
        options.get("solcast_planning_basis", "mean-lower-central")
    )
    run_id = _stable_id(
        "run", f"{__version__}|{capture.isoformat()}|{ARCHITECTURE_BASELINE_COMMIT}|{evidence_seed}"
    )
    snapshot_id = _stable_id("snapshot", run_id)

    facts = tuple(
        CanonicalInputFact(
            fact_id=_stable_id("fact", f"{snapshot_id}|{item.evidence_id}"),
            run_id=run_id,
            snapshot_id=snapshot_id,
            category=item.category,
            semantic_role=item.semantic_role,
            value=_canonical_value(item.raw_state) if item.availability == "available" else None,
            unit=item.raw_unit,
            observed_at=item.observed_at,
            availability=item.availability,
            evidence_id=item.evidence_id,
            mapping_version=item.mapping_version,
        )
        for item in evidence
    )
    calibration_source = next(
        (
            item
            for item in evidence
            if item.semantic_role == "bms_soc_calibration"
        ),
        None,
    )
    calibration_state = (
        calibration_source.raw_state.strip().casefold()
        if calibration_source is not None
        and calibration_source.raw_state is not None
        else None
    )
    calibration_active_values = {"ja", "yes", "on", "true", "1", "actief", "active"}
    calibration_inactive_values = {"nee", "no", "off", "false", "0", "inactief", "inactive"}
    bms_calibration_evidence = BMSCalibrationEvidence(
        status=(
            "active"
            if calibration_source is not None
            and calibration_source.availability == "available"
            and calibration_state in calibration_active_values
            else (
                "inactive"
                if calibration_source is not None
                and calibration_source.availability == "available"
                and calibration_state in calibration_inactive_values
                else "unavailable"
            )
        ),
        active=(
            calibration_source is not None
            and calibration_source.availability == "available"
            and calibration_state in calibration_active_values
        ),
        observed_at=(
            calibration_source.observed_at
            if calibration_source is not None
            else None
        ),
        source_entity_id=(
            calibration_source.entity_id
            if calibration_source is not None
            else None
        ),
        evidence_id=(
            calibration_source.evidence_id
            if calibration_source is not None
            else _stable_id("evidence", f"{snapshot_id}|bms-calibration-unconfigured")
        ),
        method_version="zendure-calibration-state:v1",
    )
    rte_source = next(
        (
            item
            for item in evidence
            if item.semantic_role == "storage_round_trip_efficiency"
        ),
        None,
    )
    rte_percent = (
        _canonical_value(rte_source.raw_state)
        if rte_source is not None
        and rte_source.availability == "available"
        else None
    )
    rte_available = (
        isinstance(rte_percent, float)
        and 50.0 <= rte_percent <= 100.0
        and rte_source is not None
        and rte_source.observed_at is not None
        and rte_source.entity_id is not None
    )
    rte_value = rte_percent / 100.0 if isinstance(rte_percent, float) else None
    rte_observed_at = rte_source.observed_at if rte_source is not None else None
    rte_entity_id = rte_source.entity_id if rte_source is not None else None
    storage_round_trip_efficiency = StorageRoundTripEfficiencyEvidence(
        status="available" if rte_available else "unavailable",
        round_trip_efficiency=(rte_value if rte_available else None),
        observed_at=(rte_observed_at if rte_available else None),
        source_entity_id=(rte_entity_id if rte_available else None),
        evidence_id=(
            rte_source.evidence_id
            if rte_source is not None
            else _stable_id(
                "evidence",
                f"{snapshot_id}|storage-rte-unconfigured",
            )
        ),
        method_version="zendure-total-rte-percent:v1",
    )
    published_price_points = tuple(
        point
        for item in evidence
        for point in item.price_points
    )
    price_points = tuple(
        point for point in published_price_points
        if point.ends_at > capture
    )
    price_horizon_end = max(
        (point.ends_at for point in price_points),
        default=None,
    )
    household_load_horizon_end = capture + timedelta(hours=36)
    household_load_forecast_requested = (
        household_load_fallback_power_w is not None
        or bool(household_load_observations)
    )
    horizon_end = (
        household_load_horizon_end
        if household_load_forecast_requested
        else price_horizon_end
    )
    current_storage_states = _current_storage_states_from_evidence(
        evidence,
        config=selected_storage_config,
    )
    pv_energy_intervals = tuple(
        interval
        for item in evidence
        for interval in item.pv_energy_intervals
        if horizon_end is None or interval.starts_at < horizon_end
    )
    pv_energy_timeline = (
        PVEnergyTimeline(
            timeline_id=_stable_id(
                "pv-energy-timeline",
                snapshot_id,
            ),
            run_id=run_id,
            snapshot_id=snapshot_id,
            intervals=tuple(
                sorted(
                    pv_energy_intervals,
                    key=lambda interval: interval.starts_at,
                )
            ),
        )
        if pv_energy_intervals
        else None
    )
    eligible_household_load_observations = tuple(
        (replace(observation,
                 power_w=observation.power_w-observation.identified_external_power_w,
                 identified_external_power_w=0.0)
         if (options.get("energy_device_policy_enabled", False) is True
             or options.get("energy_device_sessions_enabled", False) is True) else observation)
        for observation in household_load_observations
        if observation.sampled_at <= capture
        and (external_load_policy is None or external_load_policy.session_id is None
             or observation.external_power_observed or observation.identified_external_power_w > 0)
    )
    household_load_forecast = (
        build_historical_household_load_forecast(
            run_id=run_id,
            snapshot_id=snapshot_id,
            starts_at=capture,
            horizon_end=household_load_horizon_end,
            observations=eligible_household_load_observations,
        )
        if eligible_household_load_observations
        else None
    )
    if (
        household_load_forecast is None
        and household_load_fallback_power_w is not None
    ):
        household_load_forecast = (
            build_fallback_household_load_forecast(
                run_id=run_id,
                snapshot_id=snapshot_id,
                starts_at=capture,
                horizon_end=household_load_horizon_end,
                fallback_power_w=household_load_fallback_power_w,
                fallback_confidence=household_load_fallback_confidence,
            )
        )

    # A separate recent baseline identifies ongoing demand; historical weights
    # and the future clock-quarter forecast remain unchanged.
    guard_observations = eligible_household_load_observations + (
        (replace(household_load_observation,
                 power_w=household_load_observation.power_w
                         - household_load_observation.identified_external_power_w,
                 identified_external_power_w=0.0),)
        if household_load_observation is not None else ()
    )
    guard_baseline = build_historical_household_load_forecast(
        run_id=run_id, snapshot_id=snapshot_id,
        starts_at=capture - timedelta(hours=1), horizon_end=capture,
        observations=eligible_household_load_observations,
    ) if eligible_household_load_observations else None
    household_load_guard = assess_household_load_guard(
        observations=guard_observations, baseline=guard_baseline, assessed_at=capture,
    )
    if household_load_forecast is not None:
        household_load_forecast = apply_household_load_guard(
            household_load_forecast, household_load_guard,
        )

    if external_load_policy is not None and household_load_forecast is not None:
        household_load_forecast = apply_external_load_policy(
            household_load_forecast, external_load_policy, captured_at=capture,
        )

    snapshot = PlanningInputSnapshot(
        run_id=run_id,
        snapshot_id=snapshot_id,
        captured_at=capture,
        solcast_planning_basis=str(options.get("solcast_planning_basis", "mean-lower-central")),
        picot_version=__version__,
        architecture_baseline_commit=ARCHITECTURE_BASELINE_COMMIT,
        pipeline_contract_version=PIPELINE_CONTRACT_VERSION,
        strategy_id="strategy:no-objectives:v1",
        horizon_end=horizon_end,
        price_points=price_points,
        published_price_points=published_price_points,
        current_storage_states=current_storage_states,
        pv_energy_timeline=pv_energy_timeline,
        household_load_forecast=household_load_forecast,
        household_load_guard=household_load_guard,
        external_load_policy=external_load_policy,
        storage_mode_capability_evidence=storage_mode_capability_evidence,
        bms_calibration_evidence=bms_calibration_evidence,
        capability_snapshot_set=(
            build_storage_capability_snapshot_set(
                storage_mode_capability_evidence,
                snapshot_id=snapshot_id,
                minimum_soc=(
                    selected_storage_config.minimum_soc
                    if selected_storage_config is not None
                    and selected_storage_config.capability_id
                    == storage_mode_capability_evidence.capability_id
                    and selected_storage_config.execution_scope_id
                    == storage_mode_capability_evidence.execution_scope_id
                    else None
                ),
            )
            if storage_mode_capability_evidence is not None
            else None
        ),
        storage_physical_limits=(
            (
                StoragePhysicalLimits(
                    execution_scope_id=(
                        selected_storage_config.execution_scope_id
                    ),
                    capability_id=selected_storage_config.capability_id,
                    minimum_soc=selected_storage_config.minimum_soc,
                    maximum_soc=selected_storage_config.maximum_soc,
                    maximum_charge_input_power_w=(
                        selected_storage_config.maximum_charge_power_w
                    ),
                    maximum_discharge_output_power_w=(
                        selected_storage_config.maximum_discharge_power_w
                    ),
                    evidence_ids=("addon-configuration:storage-physical-limits",),
                    method_version="configured-storage-physical-limits:v1",
                ),
            )
            if selected_storage_config is not None
            and selected_storage_config.minimum_soc is not None
            and selected_storage_config.maximum_soc is not None
            and selected_storage_config.maximum_charge_power_w is not None
            and selected_storage_config.maximum_discharge_power_w is not None
            else ()
        ),
        storage_round_trip_efficiency=storage_round_trip_efficiency,
        household_unexpected_reserve_fraction=(
            household_unexpected_reserve_fraction
        ),
    )
    return PlanningInputBundle(
        snapshot,
        evidence,
        facts,
        started,
        finished,
        household_load_observation,
        household_load_rejection_reason,
    )
