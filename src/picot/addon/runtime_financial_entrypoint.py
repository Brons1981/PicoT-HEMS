"""Compose explicit ADR-041 export settlement evidence into the live Planner Run.

This wrapper does not alter Candidate or Evaluation logic. It only adds the
separately configured grid-export settlement forecast to the immutable planning
snapshot immediately before the existing ADR-037 readiness pipeline consumes it.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, cast

from picot.addon import runtime_snapshot_entrypoint as base
from picot.domain.forecast import ForecastKind, ForecastSeries, ForecastSet

_export_price_entity = ""
_original_run_adr037_readiness = base.run_adr037_readiness


def _live_export_price_forecast(*, captured_at: Any) -> ForecastSeries | None:
    if not _export_price_entity or not base._supervisor_token:
        return None
    try:
        raw_state = base.runtime._request_json(
            f"/api/states/{_export_price_entity}", base._supervisor_token
        )
        generic = base.runtime._price_forecast(raw_state, now=cast(Any, captured_at))
    except Exception:
        return None
    return replace(
        generic,
        forecast_id=f"ha-export-price-{captured_at.isoformat()}",
        kind=ForecastKind.GRID_EXPORT_PRICE,
        source=_export_price_entity,
    )


def _run_adr037_readiness_with_export(snapshot: Any, *args: Any, **kwargs: Any) -> Any:
    export_forecast = _live_export_price_forecast(captured_at=snapshot.captured_at)
    if export_forecast is not None:
        existing = tuple(
            series
            for series in snapshot.forecasts.series
            if series.kind is not ForecastKind.GRID_EXPORT_PRICE
        )
        snapshot = replace(
            snapshot,
            forecasts=ForecastSet(series=(*existing, export_forecast)),
        )
    return _original_run_adr037_readiness(snapshot, *args, **kwargs)


def main() -> int:
    global _export_price_entity
    with base.runtime.OPTIONS_PATH.open(encoding="utf-8") as handle:
        options = cast(dict[str, Any], json.load(handle))
    _export_price_entity = str(options.get("export_price_entity", "")).strip()
    base.run_adr037_readiness = _run_adr037_readiness_with_export
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
