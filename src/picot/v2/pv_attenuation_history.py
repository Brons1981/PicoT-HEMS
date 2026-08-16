"""Observer-only historical profile construction for V2ADR-049."""

from __future__ import annotations

from datetime import datetime

from picot.v2.contracts import PVForecastAttenuationProfile
from picot.v2.pv_attenuation_aggregation import (
    PVAttenuationAggregationConfig,
    aggregate_pv_attenuation_profile,
)
from picot.v2.pv_attenuation_eligibility import (
    PVAttenuationEligibilityConfig,
    classify_pv_attenuation_observation,
)
from picot.v2.pv_attenuation_evidence import PVAttenuationEvidenceStore


def build_pv_attenuation_profile_from_history(
    *,
    store: PVAttenuationEvidenceStore,
    installation_scope_id: str,
    evaluated_at: datetime,
    eligibility_config: PVAttenuationEligibilityConfig,
    aggregation_config: PVAttenuationAggregationConfig,
) -> PVForecastAttenuationProfile:
    """Rebuild one observer-only profile from retained observations."""
    observations = store.load()
    classified = tuple(
        classify_pv_attenuation_observation(
            target_observation_id=observation.observation_id,
            observations=observations,
            evaluated_at=evaluated_at,
            config=eligibility_config,
        )
        for observation in observations
        if observation.installation_scope_id == installation_scope_id
    )
    return aggregate_pv_attenuation_profile(
        installation_scope_id=installation_scope_id,
        observations=classified,
        evaluated_at=evaluated_at,
        config=aggregation_config,
    )
