from pathlib import Path

from picot.v2 import __version__


def test_v2_runtime_version_matches_home_assistant_addon() -> None:
    config_path = Path(__file__).parents[1] / "picot_hems" / "config.yaml"
    version_lines = [
        line
        for line in config_path.read_text(encoding="utf-8").splitlines()
        if line.startswith("version: ")
    ]

    assert len(version_lines) == 1
    addon_version = version_lines[0].partition(":")[2].strip().strip('"')
    assert __version__ == addon_version


def test_v2_ingress_release_uses_dev_13() -> None:
    assert __version__ == "2.0.0-dev.13"


def test_v2_addon_exposes_pipeline_dashboard_via_ingress() -> None:
    config_path = Path(__file__).parents[1] / "picot_hems" / "config.yaml"
    top_level = {
        key: value.strip().strip('"')
        for line in config_path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith(" ") and ":" in line
        for key, _, value in (line.partition(":"),)
    }

    assert top_level.get("ingress") == "true"
    assert top_level.get("ingress_port") == "8099"
    assert top_level.get("panel_icon") == "mdi:chart-timeline-variant"
    assert top_level.get("panel_title") == "PicoT Pipeline"
