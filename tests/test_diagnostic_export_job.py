from threading import Event
from time import monotonic, sleep

from picot.diagnostic_export_job import DiagnosticExportJob


def finished(job):
    deadline = monotonic() + 3
    while job.status()["status"] == "building" and monotonic() < deadline:
        sleep(0.001)
    assert job.status()["status"] != "building"
    return job.status()


def test_acknowledgement_progress_deduplication_and_download():
    entered, release = Event(), Event()
    job = DiagnosticExportJob()

    def build(progress):
        progress(3, 10, "Bestanden inpakken")
        entered.set()
        assert release.wait(3)
        return b"zip-result"

    accepted = job.start(build, "diagnosis.zip")
    assert accepted["status"] == "building"
    assert entered.wait(3)
    assert job.status()["completed"] == 3
    assert job.download(accepted["job_id"]) is None
    duplicate = job.start(lambda p: b"wrong", "wrong.zip")
    assert duplicate["job_id"] == accepted["job_id"]
    release.set()
    state = finished(job)
    assert state["status"] == "ready"
    assert state["size_bytes"] == 10
    assert job.download("wrong") is None
    assert job.download(accepted["job_id"]) == (b"zip-result", "diagnosis.zip")
    state["status"] = "failed"
    assert job.status()["status"] == "ready"


def test_failure_visible_and_new_request_can_retry():
    job = DiagnosticExportJob()

    def broken(progress):
        raise OSError("private path")

    first = job.start(broken, "diagnosis.zip")
    assert finished(job)["status"] == "failed"
    assert "private" not in str(job.status())
    second = job.start(lambda p: b"ok", "diagnosis.zip")
    assert second["job_id"] != first["job_id"]
    assert finished(job)["status"] == "ready"
    assert job.download(first["job_id"]) is None
    assert job.download(second["job_id"]) == (b"ok", "diagnosis.zip")



def test_addon_images_include_the_standalone_export_worker(tmp_path):
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    module = "src/picot/diagnostic_export_job.py"
    for addon in ("picot_hems", "picot_energy_devices"):
        dockerfile = (root / addon / "Dockerfile").read_text(encoding="utf-8")
        assert f"cp /tmp/picot-src/{module} " in dockerfile
    package = tmp_path / "picot"
    package.mkdir()
    (package / "__init__.py").write_text("")
    shutil.copyfile(root / module, package / "diagnostic_export_job.py")
    # The Energy Devices image includes only this generic module, not HEMS code.
    script = ("import sys; sys.path.insert(0, sys.argv[1]); "
              "from picot.diagnostic_export_job import DiagnosticExportJob; "
              "assert DiagnosticExportJob().status()['status'] == 'idle'")
    result = subprocess.run([sys.executable, "-I", "-c", script, str(tmp_path)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
