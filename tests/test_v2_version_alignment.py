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


def test_v2_visible_dutch_card_summary_batch_uses_dev_67() -> None:
    assert __version__ == "2.0.0-dev.75"


def test_v2_addon_defaults_to_detailed_solcast_today_forecast() -> None:
    config_path = Path(__file__).parents[1] / "picot_hems" / "config.yaml"
    lines = config_path.read_text(encoding="utf-8").splitlines()
    option_lines = lines[
        lines.index("options:") + 1 : lines.index("schema:")
    ]
    options = {
        key.strip(): value.strip().strip('"')
        for line in option_lines
        if line.startswith("  ") and ":" in line
        for key, _, value in (line.partition(":"),)
    }

    assert options.get("solcast_forecast_entity") == (
        "sensor.solcast_pv_forecast_voorspelling_vandaag"
    )


def test_v2_addon_exposes_validated_storage_power_sources() -> None:
    config_path = Path(__file__).parents[1] / "picot_hems" / "config.yaml"
    lines = config_path.read_text(encoding="utf-8").splitlines()
    option_lines = lines[
        lines.index("options:") + 1 : lines.index("schema:")
    ]
    schema_lines = lines[lines.index("schema:") + 1 :]
    options = {
        key.strip(): value.strip().strip('"')
        for line in option_lines
        if line.startswith("  ") and ":" in line
        for key, _, value in (line.partition(":"),)
    }

    assert options.get("zendure_signed_power_entity") == (
        "sensor.zendure_2400_ac_vermogen_aansturing"
    )
    assert options.get("zendure_power_to_house_entity") == (
        "sensor.zendure_2400_ac_vermogen_naar_huis"
    )
    assert options.get("zendure_power_from_house_entity") == (
        "sensor.zendure_2400_ac_vermogen_van_huis"
    )
    assert "  zendure_signed_power_entity: str" in schema_lines
    assert "  zendure_power_to_house_entity: str" in schema_lines
    assert "  zendure_power_from_house_entity: str" in schema_lines


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

def test_v2_addon_exposes_household_load_fallback_power() -> None:
    config_path = Path(__file__).parents[1] / "picot_hems" / "config.yaml"
    lines = config_path.read_text(encoding="utf-8").splitlines()
    option_lines = lines[
        lines.index("options:") + 1 : lines.index("schema:")
    ]
    schema_lines = lines[lines.index("schema:") + 1 :]
    options = {
        key.strip(): value.strip().strip('"')
        for line in option_lines
        if line.startswith("  ") and ":" in line
        for key, _, value in (line.partition(":"),)
    }

    assert options.get("household_load_fallback_power_w") == "500.0"
    assert (
        "  household_load_fallback_power_w: float(0,)"
        in schema_lines
    )


def test_v2_addon_exposes_explicit_pv_local_timezone() -> None:
    config_path = Path(__file__).parents[1] / "picot_hems" / "config.yaml"
    lines = config_path.read_text(encoding="utf-8").splitlines()
    option_lines = lines[
        lines.index("options:") + 1 : lines.index("schema:")
    ]
    schema_lines = lines[lines.index("schema:") + 1 :]
    options = {
        key.strip(): value.strip().strip('"')
        for line in option_lines
        if line.startswith("  ") and ":" in line
        for key, _, value in (line.partition(":"),)
    }

    assert options.get("pv_local_timezone") == "Europe/Amsterdam"
    assert "  pv_local_timezone: str" in schema_lines
