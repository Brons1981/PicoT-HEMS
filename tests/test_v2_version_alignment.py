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
