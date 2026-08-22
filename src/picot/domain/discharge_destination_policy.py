"""Generic discharge destination permission for complete Energy Paths."""

from __future__ import annotations

from enum import StrEnum


class DischargeDestinationPolicy(StrEnum):
    """Permitted destinations for energy discharged from storage."""

    HOUSEHOLD_ONLY = "household_only"
    HOUSEHOLD_PREFERRED_GRID_ALLOWED = "household_preferred_grid_allowed"
    GRID_ALLOWED_FOR_MARKET_ACTION = "grid_allowed_for_market_action"

    @property
    def permits_grid_export(self) -> bool:
        """Return whether the policy explicitly permits storage-to-grid flow."""

        return self is not DischargeDestinationPolicy.HOUSEHOLD_ONLY

    @property
    def requires_household_preference(self) -> bool:
        """Return whether household demand must be served before grid export."""

        return self in {
            DischargeDestinationPolicy.HOUSEHOLD_ONLY,
            DischargeDestinationPolicy.HOUSEHOLD_PREFERRED_GRID_ALLOWED,
        }

    @property
    def is_market_action(self) -> bool:
        """Return whether grid export belongs to a discretionary market cycle."""

        return self is DischargeDestinationPolicy.GRID_ALLOWED_FOR_MARKET_ACTION
