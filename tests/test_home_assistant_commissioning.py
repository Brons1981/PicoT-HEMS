from __future__ import annotations

from picot.commissioning.home_assistant import build_parser


def test_commissioning_defaults_to_accepted_first_call(monkeypatch) -> None:
    monkeypatch.delenv("PICOT_HA_BASE_URL", raising=False)

    args = build_parser().parse_args([])

    assert args.base_url == "http://192.168.6.26:8123"
    assert args.power_w == 1200.0


def test_commissioning_accepts_runtime_overrides(monkeypatch) -> None:
    monkeypatch.setenv("PICOT_HA_BASE_URL", "http://homeassistant.local:8123")

    args = build_parser().parse_args(["--power-w", "800"])

    assert args.base_url == "http://homeassistant.local:8123"
    assert args.power_w == 800.0
