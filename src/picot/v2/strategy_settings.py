"""Deterministic user-setting mapping; never selects or executes a plan."""

from dataclasses import dataclass
from math import isfinite

METHOD_VERSION = "strategy-capacity-mapping:v1"
LABELS = ("Zelfverbruik", "Meer zelfverbruik", "Gebalanceerd", "Meer handel")


def valid_percent(value: object) -> float:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not isfinite(value) or not 0 <= value <= 100):
        raise ValueError("Trading percentage must be finite between 0 and 100")
    return float(value)


@dataclass(frozen=True, slots=True)
class StrategySetting:
    position: int
    trade_ceiling_percent: float

    def __post_init__(self) -> None:
        if type(self.position) is not int or self.position not in range(4):
            raise ValueError("Strategy position must be 0..3; pure trading is not available yet")
        valid_percent(self.trade_ceiling_percent)

    @property
    def effective_percent(self) -> float:
        return self.trade_ceiling_percent * self.position / 3

    def as_public_dict(self) -> dict[str, object]:
        return {
            "method_version": METHOD_VERSION,
            "position": self.position,
            "label": LABELS[self.position],
            "capacity_factor": self.position / 3,
            "effective_trading_soc_percent": self.effective_percent,
            "trade_ceiling_percent": self.trade_ceiling_percent,
        }


def migrate_effective_maximum(value: object) -> StrategySetting:
    maximum = valid_percent(value)
    # Preserve the current effective maximum. A high legacy cap cannot fit at
    # two-thirds of a physical 100% ceiling, so retain it at position three.
    if maximum <= 100 * 2 / 3:
        return StrategySetting(2, maximum * 1.5)
    return StrategySetting(3, maximum)
