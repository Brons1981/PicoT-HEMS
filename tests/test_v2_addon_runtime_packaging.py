from pathlib import Path


def test_addon_image_packages_v2_runtime_dependencies() -> None:
    dockerfile = (
        Path(__file__).parents[1] / "picot_hems" / "Dockerfile"
    ).read_text(encoding="utf-8")

    assert (
        "cp -R /tmp/picot-src/src/picot/domain "
        "/opt/picot/picot/domain"
    ) in dockerfile
    assert (
        "cp -R /tmp/picot-src/src/picot/adapters "
        "/opt/picot/picot/adapters"
    ) in dockerfile
    assert (
        "cp -R /tmp/picot-src/src/picot/planner "
        "/opt/picot/picot/planner"
    ) in dockerfile
