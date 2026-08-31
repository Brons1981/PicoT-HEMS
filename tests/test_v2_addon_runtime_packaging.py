import ast
import re
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _canonical_runtime_components() -> set[str]:
    package_root = ROOT / "src" / "picot"
    pending = ["v2"]
    required: set[str] = set()

    while pending:
        component = pending.pop()
        if component in required:
            continue
        required.add(component)
        component_dir = package_root / component
        component_file = package_root / f"{component}.py"
        sources = (
            tuple(component_dir.rglob("*.py"))
            if component_dir.is_dir()
            else (component_file,)
        )
        for source in sources:
            tree = ast.parse(source.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names: tuple[str, ...] = ()
                if isinstance(node, ast.ImportFrom) and node.module:
                    names = (node.module,)
                elif isinstance(node, ast.Import):
                    names = tuple(alias.name for alias in node.names)
                for name in names:
                    if not name.startswith("picot."):
                        continue
                    dependency = name.split(".", maxsplit=2)[1]
                    if (
                        (package_root / dependency).is_dir()
                        or (package_root / f"{dependency}.py").is_file()
                    ):
                        pending.append(dependency)

    return required


def _docker_packaged_components(dockerfile: str) -> set[str]:
    copied = re.findall(
        r"cp(?: -R)? /tmp/picot-src/src/picot/"
        r"([A-Za-z_][A-Za-z0-9_]*(?:\.py)?) /opt/picot/picot/",
        dockerfile,
    )
    return {component.removesuffix(".py") for component in copied}


def test_addon_image_packages_v2_runtime_dependencies() -> None:
    dockerfile = (ROOT / "picot_hems" / "Dockerfile").read_text(encoding="utf-8")

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


def test_addon_image_packages_complete_canonical_import_closure() -> None:
    dockerfile = (ROOT / "picot_hems" / "Dockerfile").read_text(encoding="utf-8")

    required = _canonical_runtime_components()
    packaged = _docker_packaged_components(dockerfile)

    assert required <= packaged, f"missing canonical runtime components: {required - packaged}"
    assert "addon" not in packaged
