"""Persistent, validated user rules for the canonical planning strategy.

The store is deliberately independent from Home Assistant add-on options.  An
option may seed the first revision, but after migration this file is the sole
source of truth for user-owned planning boundaries.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from threading import Lock
from typing import cast

from picot.domain.market_user_rule import MarketUserRule

SCHEMA_VERSION = 2
METHOD_VERSION = "canonical-user-rules:v2"


@dataclass(frozen=True, slots=True)
class UserRuleProfile:
    revision: int
    updated_at: datetime
    preserve_pv_during_grid_charge: bool
    maximum_trading_soc_percent: float
    saldering_energy_tax_credit_enabled: bool
    source: str
    market_minimum_spread_eur_per_kwh: float | None = None
    market_recovery_required: bool = False
    market_minimum_net_margin_eur_per_kwh: float = 0.05

    def __post_init__(self) -> None:
        if self.revision < 1:
            raise ValueError("User-rule revision must be positive")
        if self.updated_at.tzinfo is None or self.updated_at.utcoffset() is None:
            raise ValueError("User-rule update time must be timezone-aware")
        if not 0.0 <= self.maximum_trading_soc_percent <= 100.0:
            raise ValueError("Maximum trading SoC must be between 0 and 100 percent")
        if self.source not in {"addon_option_migration", "strategy_dashboard"}:
            raise ValueError("User-rule source must be explicit")
        if not isinstance(self.market_recovery_required, bool):
            raise ValueError("Market recovery choice must be boolean")
        if self.market_minimum_net_margin_eur_per_kwh is None:
            raise ValueError("Market net margin must be numeric")
        for value in (
            self.market_minimum_spread_eur_per_kwh,
            self.market_minimum_net_margin_eur_per_kwh,
        ):
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
                or value < 0
            ):
                raise ValueError("Market price thresholds must be finite nonnegative EUR/kWh")

    def market_rule(self) -> MarketUserRule | None:
        if self.market_minimum_spread_eur_per_kwh is None or self.maximum_trading_soc_percent == 0:
            return None
        return MarketUserRule(
            "user-market",
            self.revision,
            self.maximum_trading_soc_percent / 100,
            self.market_minimum_spread_eur_per_kwh,
            self.market_recovery_required,
            self.market_minimum_net_margin_eur_per_kwh,
        )

    def as_public_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "method_version": METHOD_VERSION,
            "revision": self.revision,
            "updated_at": self.updated_at.isoformat(),
            "preserve_pv_during_grid_charge": self.preserve_pv_during_grid_charge,
            "maximum_trading_soc_percent": self.maximum_trading_soc_percent,
            "saldering_energy_tax_credit_enabled": self.saldering_energy_tax_credit_enabled,
            "source": self.source,
            "market_minimum_spread_eur_per_kwh": self.market_minimum_spread_eur_per_kwh,
            "market_recovery_required": self.market_recovery_required,
            "market_minimum_net_margin_eur_per_kwh": self.market_minimum_net_margin_eur_per_kwh,
        }


class UserRuleStore:
    """Atomically persist one immutable, monotonically versioned profile."""

    def __init__(
        self,
        path: Path,
        *,
        migrated_trading_soc_percent: float,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._path = path
        self._lock = Lock()
        self._now = now or (lambda: datetime.now(UTC))
        self._profile = self._load_or_migrate(migrated_trading_soc_percent)

    def current(self) -> UserRuleProfile:
        with self._lock:
            return self._profile

    def update(
        self,
        *,
        preserve_pv_during_grid_charge: object,
        maximum_trading_soc_percent: object,
        saldering_energy_tax_credit_enabled: object | None = None,
        market_minimum_spread_eur_per_kwh: object = ...,
        market_recovery_required: object = ...,
        market_minimum_net_margin_eur_per_kwh: object = ...,
    ) -> UserRuleProfile:
        if not isinstance(preserve_pv_during_grid_charge, bool):
            raise ValueError("PV-preservation rule must be boolean")
        if isinstance(maximum_trading_soc_percent, bool) or not isinstance(
            maximum_trading_soc_percent, (int, float)
        ):
            raise ValueError("Maximum trading SoC must be numeric")
        if saldering_energy_tax_credit_enabled is None:
            saldering_energy_tax_credit_enabled = (
                self.current().saldering_energy_tax_credit_enabled
            )
        if not isinstance(saldering_energy_tax_credit_enabled, bool):
            raise ValueError("Saldering energy-tax rule must be boolean")
        with self._lock:
            updated = UserRuleProfile(
                revision=self._profile.revision + 1,
                updated_at=self._now(),
                preserve_pv_during_grid_charge=preserve_pv_during_grid_charge,
                maximum_trading_soc_percent=float(maximum_trading_soc_percent),
                saldering_energy_tax_credit_enabled=saldering_energy_tax_credit_enabled,
                source="strategy_dashboard",
                market_minimum_spread_eur_per_kwh=(
                    self._profile.market_minimum_spread_eur_per_kwh
                    if market_minimum_spread_eur_per_kwh is ...
                    else cast(float | None, market_minimum_spread_eur_per_kwh)
                ),
                market_recovery_required=(
                    self._profile.market_recovery_required
                    if market_recovery_required is ...
                    else cast(bool, market_recovery_required)
                ),
                market_minimum_net_margin_eur_per_kwh=(
                    self._profile.market_minimum_net_margin_eur_per_kwh
                    if market_minimum_net_margin_eur_per_kwh is ...
                    else cast(float, market_minimum_net_margin_eur_per_kwh)
                ),
            )
            self._write(updated)
            self._profile = updated
            return updated

    def _load_or_migrate(self, migrated_percent: float) -> UserRuleProfile:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            profile = UserRuleProfile(
                revision=1,
                updated_at=self._now(),
                preserve_pv_during_grid_charge=True,
                maximum_trading_soc_percent=float(migrated_percent),
                saldering_energy_tax_credit_enabled=True,
                source="addon_option_migration",
            )
            self._write(profile)
            return profile
        if not isinstance(raw, dict) or raw.get("schema_version") not in {1, SCHEMA_VERSION}:
            raise ValueError("Unsupported canonical user-rule document")
        preserve_pv = raw.get("preserve_pv_during_grid_charge")
        if not isinstance(preserve_pv, bool):
            raise ValueError("Stored PV-preservation rule must be boolean")
        saldering_tax = raw.get("saldering_energy_tax_credit_enabled", True)
        if not isinstance(saldering_tax, bool):
            raise ValueError("Stored saldering energy-tax rule must be boolean")
        return UserRuleProfile(
            revision=int(raw["revision"]),
            updated_at=datetime.fromisoformat(str(raw["updated_at"])),
            preserve_pv_during_grid_charge=preserve_pv,
            maximum_trading_soc_percent=float(raw["maximum_trading_soc_percent"]),
            saldering_energy_tax_credit_enabled=saldering_tax,
            source=str(raw["source"]),
            market_minimum_spread_eur_per_kwh=raw.get("market_minimum_spread_eur_per_kwh"),
            market_recovery_required=raw.get("market_recovery_required", False),
            market_minimum_net_margin_eur_per_kwh=raw.get(
                "market_minimum_net_margin_eur_per_kwh", 0.05
            ),
        )

    def _write(self, profile: UserRuleProfile) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(self._path.suffix + ".tmp")
        payload = profile.as_public_dict()
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self._path)
