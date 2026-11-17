"""Persistent, validated user rules for the canonical planning strategy.

The store is deliberately independent from Home Assistant add-on options.  An
option may seed the first revision, but after migration this file is the sole
source of truth for user-owned planning boundaries.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from threading import Lock
from typing import cast
from zoneinfo import ZoneInfo

from picot.domain.market_user_rule import MarketUserRule
from picot.domain.solar_export_bonus import SolarExportBonusPolicy
from picot.v2.strategy_settings import StrategySetting, migrate_effective_maximum, valid_percent

SCHEMA_VERSION = 2
METHOD_VERSION = "canonical-user-rules:v4"


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
    market_wear_eur_per_kwh: float = 0.05
    solar_export_bonus: SolarExportBonusPolicy | None = None
    strategy_position: int | None = None
    strategy_trade_ceiling_percent: float | None = None

    def __post_init__(self) -> None:
        if self.revision < 1:
            raise ValueError("User-rule revision must be positive")
        if self.updated_at.tzinfo is None or self.updated_at.utcoffset() is None:
            raise ValueError("User-rule update time must be timezone-aware")
        valid_percent(self.maximum_trading_soc_percent)
        mapping = self.strategy_setting()
        if abs(mapping.effective_percent - self.maximum_trading_soc_percent) > 1e-9:
            raise ValueError("Strategy mapping must match the effective trading maximum")
        if (isinstance(self.market_wear_eur_per_kwh, bool)
                or not isinstance(self.market_wear_eur_per_kwh, (int, float))
                or not isfinite(self.market_wear_eur_per_kwh)
                or not 0 <= self.market_wear_eur_per_kwh <= 1):
            raise ValueError("Market wear must be finite between 0 and 1 EUR/kWh")
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

    def strategy_setting(self) -> StrategySetting:
        if self.strategy_position is None and self.strategy_trade_ceiling_percent is None:
            return migrate_effective_maximum(self.maximum_trading_soc_percent)
        if self.strategy_position is None or self.strategy_trade_ceiling_percent is None:
            raise ValueError("Strategy position and ceiling must be stored together")
        return StrategySetting(self.strategy_position, self.strategy_trade_ceiling_percent)

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
        setting = self.strategy_setting()
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
            "market_wear_eur_per_kwh": self.market_wear_eur_per_kwh,
            "solar_export_bonus": _solar_policy_dict(self.solar_export_bonus),
            "strategy_position": setting.position,
            "strategy_trade_ceiling_percent": setting.trade_ceiling_percent,
            "strategy_mapping": setting.as_public_dict(),
        }


class UserRuleStore:
    """Atomically persist one immutable, monotonically versioned profile."""

    def __init__(
        self,
        path: Path,
        *,
        migrated_trading_soc_percent: float,
        migrated_wear_eur_per_kwh: float = 0.05,
        local_timezone_name: str = "Europe/Amsterdam",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._path = path
        self._lock = Lock()
        self._now = now or (lambda: datetime.now(UTC))
        self._timezone_name = ZoneInfo(local_timezone_name).key
        self._profile = self._load_or_migrate(
            migrated_trading_soc_percent, migrated_wear_eur_per_kwh
        )

    def current(self) -> UserRuleProfile:
        with self._lock:
            return self._profile

    def update(
        self,
        *,
        preserve_pv_during_grid_charge: object = ...,
        maximum_trading_soc_percent: object = ...,
        saldering_energy_tax_credit_enabled: object | None = None,
        market_minimum_spread_eur_per_kwh: object = ...,
        market_recovery_required: object = ...,
        market_minimum_net_margin_eur_per_kwh: object = ...,
        market_wear_eur_per_kwh: object = ...,
        solar_export_bonus: object = ...,
        strategy_position: object = ...,
        strategy_trade_ceiling_percent: object = ...,
    ) -> UserRuleProfile:
        with self._lock:
            if preserve_pv_during_grid_charge is ...:
                preserve_pv_during_grid_charge = self._profile.preserve_pv_during_grid_charge
            if not isinstance(preserve_pv_during_grid_charge, bool):
                raise ValueError("PV-preservation rule must be boolean")
            if saldering_energy_tax_credit_enabled is None:
                saldering_energy_tax_credit_enabled = (
                    self._profile.saldering_energy_tax_credit_enabled
                )
            if not isinstance(saldering_energy_tax_credit_enabled, bool):
                raise ValueError("Saldering energy-tax rule must be boolean")
            setting = self._profile.strategy_setting()
            new_strategy = strategy_position is not ... or strategy_trade_ceiling_percent is not ...
            if new_strategy:
                if maximum_trading_soc_percent is not ...:
                    raise ValueError("Do not combine a legacy maximum with strategy settings")
                setting = StrategySetting(
                    setting.position if strategy_position is ... else cast(int, strategy_position),
                    setting.trade_ceiling_percent if strategy_trade_ceiling_percent is ...
                    else valid_percent(strategy_trade_ceiling_percent),
                )
            elif maximum_trading_soc_percent is not ...:
                maximum = valid_percent(maximum_trading_soc_percent)
                if maximum != self._profile.maximum_trading_soc_percent:
                    setting = migrate_effective_maximum(maximum)
            changed_at = self._now()
            updated = UserRuleProfile(
                revision=self._profile.revision + 1,
                updated_at=changed_at,
                preserve_pv_during_grid_charge=preserve_pv_during_grid_charge,
                maximum_trading_soc_percent=setting.effective_percent,
                strategy_position=setting.position,
                strategy_trade_ceiling_percent=setting.trade_ceiling_percent,
                saldering_energy_tax_credit_enabled=saldering_energy_tax_credit_enabled,
                source="strategy_dashboard",
                solar_export_bonus=(
                    self._profile.solar_export_bonus if solar_export_bonus is ...
                    else _updated_solar_policy(solar_export_bonus, self._profile.solar_export_bonus,
                                               changed_at, self._timezone_name)
                ),
                market_wear_eur_per_kwh=(
                    self._profile.market_wear_eur_per_kwh
                    if market_wear_eur_per_kwh is ...
                    else cast(float, market_wear_eur_per_kwh)
                ),
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

    def _load_or_migrate(self, migrated_percent: float, migrated_wear: float) -> UserRuleProfile:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            setting = migrate_effective_maximum(migrated_percent)
            profile = UserRuleProfile(
                revision=1,
                updated_at=self._now(),
                preserve_pv_during_grid_charge=True,
                maximum_trading_soc_percent=float(migrated_percent),
                saldering_energy_tax_credit_enabled=True,
                source="addon_option_migration",
                market_wear_eur_per_kwh=migrated_wear,
                strategy_position=setting.position,
                strategy_trade_ceiling_percent=setting.trade_ceiling_percent,
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
        if "strategy_position" in raw or "strategy_trade_ceiling_percent" in raw:
            setting = StrategySetting(cast(int, raw.get("strategy_position")),
                                      cast(float, raw.get("strategy_trade_ceiling_percent")))
        else:
            setting = migrate_effective_maximum(raw["maximum_trading_soc_percent"])
        return UserRuleProfile(
            revision=int(raw["revision"]),
            updated_at=datetime.fromisoformat(str(raw["updated_at"])),
            preserve_pv_during_grid_charge=preserve_pv,
            maximum_trading_soc_percent=float(raw["maximum_trading_soc_percent"]),
            saldering_energy_tax_credit_enabled=saldering_tax,
            source=str(raw["source"]),
            strategy_position=setting.position,
            strategy_trade_ceiling_percent=setting.trade_ceiling_percent,
            market_wear_eur_per_kwh=raw.get("market_wear_eur_per_kwh", migrated_wear),
            solar_export_bonus=_load_solar_policy(raw.get("solar_export_bonus")),
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


def _solar_policy_dict(policy: SolarExportBonusPolicy | None) -> dict[str, object] | None:
    if policy is None:
        return None
    return {key: value.isoformat() if isinstance(value, datetime) else value
            for key, value in asdict(policy).items()}


def _load_solar_policy(raw: object) -> SolarExportBonusPolicy | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("Stored solar bonus must be an object")
    return SolarExportBonusPolicy(
        enabled=raw["enabled"], effective_from=datetime.fromisoformat(raw["effective_from"]),
        latitude=raw["latitude"], longitude=raw["longitude"],
        annual_exported_kwh=raw.get("annual_exported_kwh"),
        annual_exported_at=(datetime.fromisoformat(raw["annual_exported_at"])
                            if raw.get("annual_exported_at") else None),
        timezone_name=raw["timezone_name"],
    )


def _updated_solar_policy(
    raw: object, previous: SolarExportBonusPolicy | None, now: datetime, timezone_name: str,
) -> SolarExportBonusPolicy | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("enabled"), bool):
        raise ValueError("Solar bonus requires an explicit enabled choice")
    latitude, longitude = raw.get("latitude"), raw.get("longitude")
    if previous is None and not raw["enabled"] and latitude is None and longitude is None:
        return None
    annual = raw.get("annual_exported_kwh")
    reanchor = raw.get("confirm_annual_export", False)
    if not isinstance(reanchor, bool):
        raise ValueError("Annual export confirmation must be boolean")
    anchor = previous.annual_exported_at if previous is not None else None
    if annual is None:
        anchor = None
    elif (previous is None or annual != previous.annual_exported_kwh or reanchor
          or anchor is None):
        anchor = now
    unchanged = (previous is not None and raw["enabled"] == previous.enabled
                 and latitude == previous.latitude and longitude == previous.longitude
                 and annual == previous.annual_exported_kwh
                 and anchor == previous.annual_exported_at)
    return SolarExportBonusPolicy(
        enabled=raw["enabled"],
        effective_from=previous.effective_from if unchanged and previous is not None else now,
        latitude=cast(float, latitude), longitude=cast(float, longitude),
        annual_exported_kwh=annual,
        annual_exported_at=anchor, timezone_name=timezone_name,
    )
