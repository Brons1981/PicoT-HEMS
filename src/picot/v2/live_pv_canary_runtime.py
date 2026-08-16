"""Runtime boundary for the controlled live PV mode canary."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from picot.adapters.home_assistant import (
    HomeAssistantAdapter,
    HomeAssistantDispatcher,
)
from picot.adapters.home_assistant_http import HomeAssistantHttpTransport
from picot.domain.execution import ExecutionPrimitiveRequest
from picot.domain.execution_primitive import ExecutionPrimitive
from picot.domain.home_assistant import (
    HomeAssistantCommandMapping,
    HomeAssistantDispatchMode,
)
from picot.v2.contracts import CanonicalPipelineRun
from picot.v2.live_pv_mode_strategy import (
    NOM_VENDOR_MODE,
    SMART_DISCHARGE_VENDOR_MODE,
    LivePVModeInput,
    LivePVModeStrategy,
)
from picot.v2.planning_input import PlanningInputBundle
from picot.v2.projection import Card

DispatchVendorMode = Callable[[str, str], str]
SUPERVISOR_BASE_URL = "http://supervisor/core"


def active_pv_charge_window(
    run: CanonicalPipelineRun,
    *,
    at: datetime,
) -> bool:
    """Return whether the winning plan has a due PV-only charge segment."""
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("at must be timezone-aware")
    return any(
        segment.starts_at <= at < segment.ends_at
        and segment.primitive
        in {
            ExecutionPrimitive.BALANCE_CHARGE_ONLY,
            ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
        }
        and segment.charge_source_policy == "pv_only"
        for plan in run.execution_plan_set.plans
        for segment in plan.segments
    )


@dataclass(frozen=True, slots=True)
class LivePVCanaryResult:
    """Explainable runtime outcome suitable for dashboard projection."""

    status: str
    requested_vendor_mode: str | None
    reason: str
    normal_result: str


@dataclass(frozen=True, slots=True)
class LivePVRuntimeEvidence:
    """Atomic live evidence needed by the canary strategy."""

    current_vendor_mode: str
    battery_power_w: float
    observed_at: datetime
    manual_override_active: bool


def build_live_pv_mode_input(
    run: CanonicalPipelineRun,
    *,
    evidence: LivePVRuntimeEvidence,
    at: datetime,
    live_enabled: bool,
) -> LivePVModeInput:
    """Combine the winning plan with one fresh live evidence sample."""
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("at must be timezone-aware")
    age_seconds = max(0.0, (at - evidence.observed_at).total_seconds())
    return LivePVModeInput(
        now=at,
        current_vendor_mode=evidence.current_vendor_mode,
        charge_window_active=active_pv_charge_window(run, at=at),
        battery_power_w=evidence.battery_power_w,
        evidence_age_seconds=age_seconds,
        manual_override_active=evidence.manual_override_active,
        live_enabled=live_enabled,
    )


def live_pv_runtime_evidence(
    bundle: PlanningInputBundle,
    *,
    sampled_at: datetime,
) -> LivePVRuntimeEvidence | None:
    """Extract fail-closed Zendure mode and signed-power evidence."""
    if sampled_at.tzinfo is None or sampled_at.utcoffset() is None:
        raise ValueError("sampled_at must be timezone-aware")
    provenance = bundle.snapshot.storage_mode_control_provenance
    power_fact = next(
        (
            fact
            for fact in bundle.facts
            if fact.semantic_role == "storage_power_signed"
            and fact.availability == "available"
            and isinstance(fact.value, (int, float))
            and not isinstance(fact.value, bool)
            and fact.observed_at is not None
        ),
        None,
    )
    if provenance is None or power_fact is None:
        return None
    assert power_fact.observed_at is not None
    power_value = power_fact.value
    assert isinstance(power_value, (int, float))
    assert not isinstance(power_value, bool)
    return LivePVRuntimeEvidence(
        current_vendor_mode=provenance.observed_vendor_mode,
        battery_power_w=float(power_value),
        observed_at=min(provenance.observed_at, sampled_at),
        manual_override_active=provenance.manual_override_active,
    )


def project_live_pv_canary_result(
    result: LivePVCanaryResult,
    *,
    captured_at: datetime,
    live_enabled: bool,
) -> Card:
    """Project the exact canary outcome as one Dutch dashboard card."""
    return Card(
        "sensor.picot_v2_live_pv_canary",
        result.status,
        {
            "captured_at": captured_at.isoformat(),
            "requested_vendor_mode": result.requested_vendor_mode,
            "reason": result.reason,
            "normal_result": result.normal_result,
            "control_change_allowed": live_enabled,
            "observer_only": not live_enabled,
        },
    )


@dataclass(slots=True)
class LivePVCanaryRuntime:
    """Apply a strategy decision through one injected adapter boundary."""

    dispatch: DispatchVendorMode
    strategy: LivePVModeStrategy = field(default_factory=LivePVModeStrategy)
    _pending_vendor_mode: str | None = None

    def apply(
        self,
        value: LivePVModeInput,
        *,
        target_entity: str,
    ) -> LivePVCanaryResult:
        if not target_entity.strip():
            raise ValueError("target_entity must be explicit")
        if self._pending_vendor_mode == value.current_vendor_mode:
            self.strategy.record_applied_mode(
                value.current_vendor_mode,
                applied_at=value.now,
            )
            self._pending_vendor_mode = None

        decision = self.strategy.evaluate(value)
        requested = decision.requested_vendor_mode
        if requested is None:
            return LivePVCanaryResult(
                status="held",
                requested_vendor_mode=None,
                reason=decision.reason,
                normal_result=_held_result(decision.reason),
            )
        if not decision.dispatch_allowed:
            return LivePVCanaryResult(
                status="observer_only",
                requested_vendor_mode=requested,
                reason=decision.reason,
                normal_result=(
                    f"PicoT zou Zendure nu naar {requested} schakelen, "
                    "maar de live-canary staat op Observer."
                ),
            )
        if self._pending_vendor_mode == requested:
            return LivePVCanaryResult(
                status="awaiting_mode_feedback",
                requested_vendor_mode=requested,
                reason="duplicate_request_blocked",
                normal_result=(
                    "PicoT wacht op bevestiging van de vorige "
                    f"Zendure-opdracht: {requested}."
                ),
            )

        status = self.dispatch(requested, target_entity)
        if status == "dispatched":
            self._pending_vendor_mode = requested
        return LivePVCanaryResult(
            status=status,
            requested_vendor_mode=requested,
            reason=decision.reason,
            normal_result=_dispatch_result(requested, status),
        )


@dataclass(frozen=True, slots=True)
class HomeAssistantLivePVModeAdapter:
    """Translate and dispatch only the two approved canary vendor modes."""

    token: str
    requested_at: Callable[[], datetime]

    def __call__(self, vendor_mode: str, target_entity: str) -> str:
        primitive = {
            NOM_VENDOR_MODE: ExecutionPrimitive.BALANCE_BIDIRECTIONAL,
            SMART_DISCHARGE_VENDOR_MODE: (
                ExecutionPrimitive.BALANCE_DISCHARGE_ONLY
            ),
        }.get(vendor_mode)
        if primitive is None:
            raise ValueError("vendor mode is outside the live PV canary")
        now = self.requested_at()
        request = ExecutionPrimitiveRequest(
            request_id=f"live-pv-canary-{now.isoformat()}",
            plan_set_id="live-pv-canary-plan-set",
            plan_id="live-pv-canary-plan",
            plan_revision=1,
            segment_id=f"live-pv-canary-{now.isoformat()}",
            execution_scope_id="home-battery",
            capability_id="storage-capability-home-battery",
            primitive=primitive,
            requested_at=now,
        )
        mapping = HomeAssistantCommandMapping(
            mapping_id=f"live-pv-canary-{primitive.value}-v1",
            mapping_version=1,
            capability_id=request.capability_id,
            execution_scope_id=request.execution_scope_id,
            primitive=primitive,
            domain="input_select",
            service="select_option",
            entity_id=target_entity,
            value_key="option",
            fixed_value=vendor_mode,
        )
        call = HomeAssistantAdapter().translate(
            request,
            mapping,
            created_at=now,
            dispatch_mode=HomeAssistantDispatchMode.LIVE,
        )
        transport = HomeAssistantHttpTransport(
            base_url=SUPERVISOR_BASE_URL,
            access_token=self.token,
            transport_mode=HomeAssistantDispatchMode.LIVE,
        )
        result = HomeAssistantDispatcher().dispatch(
            call,
            attempted_at=now,
            transport=transport,
        )
        return result.status.value


def _dispatch_result(vendor_mode: str, status: str) -> str:
    if status != "dispatched":
        return f"De Zendure-opdracht voor {vendor_mode} is niet uitgevoerd ({status})."
    if vendor_mode == NOM_VENDOR_MODE:
        return (
            "PicoT heeft Zendure naar Nul op de meter geschakeld "
            "voor het actieve PV-laadvenster."
        )
    if vendor_mode == SMART_DISCHARGE_VENDOR_MODE:
        return (
            "PicoT heeft Zendure teruggeschakeld naar Alleen slim ontladen "
            "na het aanhoudende omslagpunt."
        )
    return f"PicoT heeft Zendure naar {vendor_mode} geschakeld."


def _held_result(reason: str) -> str:
    messages = {
        "manual_override_active": (
            "PicoT stuurt niet omdat een handmatige Zendure-keuze actief is."
        ),
        "evidence_stale": (
            "PicoT stuurt niet omdat de actuele batterijgegevens te oud zijn."
        ),
        "discharge_turning_point_pending": (
            "PicoT wacht tot het omslagpunt vijf minuten onafgebroken aanhoudt."
        ),
        "smart_discharge_minimum_hold_active": (
            "PicoT houdt Alleen slim ontladen minimaal vijftien minuten vast."
        ),
    }
    return messages.get(reason, "PicoT houdt de huidige Zendure-modus vast.")
