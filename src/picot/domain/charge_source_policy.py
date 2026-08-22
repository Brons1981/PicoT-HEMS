"""Generic charging energy-source permission for planned Energy Paths.

ADR-037 requires charging power and charging source permission to remain
separate. CHARGE_AT_POWER describes what a device may do; ChargeSourcePolicy
describes which energy sources a planned charging segment may rely on.
"""

from __future__ import annotations

from enum import StrEnum


class ChargeSourcePolicy(StrEnum):
    """Permitted energy sources for a charging segment in an Energy Path.

    The policy is declarative evidence carried by planning. It is not an
    execution command and does not itself select a charging window.
    """

    PV_ONLY = "pv_only"
    PV_PREFERRED_GRID_ALLOWED = "pv_preferred_grid_allowed"

    @property
    def permits_grid_import(self) -> bool:
        """Return whether this policy explicitly permits grid supplementation."""

        return self is ChargeSourcePolicy.PV_PREFERRED_GRID_ALLOWED

    @property
    def requires_pv_preference(self) -> bool:
        """All currently supported policies preserve PV as the preferred source."""

        return True
