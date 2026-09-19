"""Self-contained checks; no dependency on unpublished HEMS changes."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1]


class ProbePackageTests(unittest.TestCase):
    def test_manual_isolation(self):
        c = json.loads((APP / "config.json").read_text())
        self.assertEqual((c["startup"], c["boot"]), ("once", "manual_only"))
        self.assertEqual(c["map"], [])
        self.assertEqual(c["ports"], {})
        for key in (
            "homeassistant_api",
            "hassio_api",
            "docker_api",
            "host_network",
            "host_pid",
            "full_access",
        ):
            self.assertFalse(c[key])
        self.assertTrue(c["apparmor"])
        self.assertFalse(c.get("privileged"))

    def test_bundled_hashes(self):
        for source, digest in json.loads((APP / "source-manifest.json").read_text()).items():
            target = (
                APP / "probe.py"
                if source.startswith("tools/")
                else (APP / "runtime/picot/v2/passive_history" / Path(source).name)
            )
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), digest)

    def test_standalone_probe(self):
        with tempfile.TemporaryDirectory() as d:
            sentinel = Path(d) / "keep.txt"
            sentinel.write_text("keep")
            run = subprocess.run(
                [sys.executable, str(APP / "probe.py"), "--scratch-parent", d],
                cwd=d,
                env=os.environ | {"PYTHONPATH": str(APP / "runtime")},
                capture_output=True,
                text=True,
                timeout=55,
                check=False,
            )
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertTrue(json.loads(run.stdout)["workload_complete"])
            self.assertEqual(list(Path(d).iterdir()), [sentinel])
            self.assertEqual(sentinel.read_text(), "keep")
