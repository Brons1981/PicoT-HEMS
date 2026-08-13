"""Connector safety test: ordinary Python function."""

from time import perf_counter


def elapsed_ms(started: float) -> float:
    return round((perf_counter() - started) * 1000.0, 3)
