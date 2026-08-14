import pytest

from picot.v2 import live_runtime


@pytest.mark.parametrize(
    ("options", "expected_power_w"),
    (
        ({}, 500.0),
        ({"household_load_fallback_power_w": 750.0}, 750.0),
        ({"household_load_fallback_power_w": "625.5"}, 625.5),
    ),
)
def test_live_planning_input_passes_household_load_fallback_to_assembly(
    monkeypatch: object,
    options: dict[str, object],
    expected_power_w: float,
) -> None:
    sentinel = object()
    calls: list[tuple[str, float]] = []

    def fake_assemble_planning_input(
        token: str,
        *,
        household_load_fallback_power_w: float,
    ) -> object:
        calls.append((token, household_load_fallback_power_w))
        return sentinel

    monkeypatch.setattr(  # type: ignore[attr-defined]
        live_runtime,
        "assemble_planning_input",
        fake_assemble_planning_input,
    )

    result = live_runtime._load_live_planning_input("token", options)

    assert result is sentinel
    assert calls == [("token", expected_power_w)]


@pytest.mark.parametrize(
    "invalid_power_w",
    (
        None,
        "not-a-number",
        0,
        -1,
        float("nan"),
        float("inf"),
    ),
)
def test_live_planning_input_rejects_invalid_household_load_fallback(
    monkeypatch: object,
    invalid_power_w: object,
) -> None:
    def unexpected_assembly(*args: object, **kwargs: object) -> None:
        pytest.fail("assemble_planning_input must not run with invalid configuration")

    monkeypatch.setattr(  # type: ignore[attr-defined]
        live_runtime,
        "assemble_planning_input",
        unexpected_assembly,
    )

    with pytest.raises(
        ValueError,
        match="household_load_fallback_power_w must be a finite positive number",
    ):
        live_runtime._load_live_planning_input(
            "token",
            {"household_load_fallback_power_w": invalid_power_w},
        )
