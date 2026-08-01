"""Vendor-independent execution primitives from ADR-015."""

from enum import StrEnum


class ExecutionPrimitive(StrEnum):
    """Generic desired energy behaviour understood by PicoT Core."""

    STANDBY = "standby"
    STOP_ALL = "stop_all"
    BALANCE_BIDIRECTIONAL = "balance_bidirectional"
    BALANCE_CHARGE_ONLY = "balance_charge_only"
    BALANCE_DISCHARGE_ONLY = "balance_discharge_only"
    CHARGE_AT_POWER = "charge_at_power"
    DISCHARGE_AT_POWER = "discharge_at_power"
