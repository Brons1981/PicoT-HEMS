from __future__ import annotations

import json
from io import BytesIO
from zipfile import ZipFile

from picot.v2.diagnostic_downloads import diagnostic_zip, incident_overview


def test_incident_overview_compacts_entity_facts(tmp_path) -> None:
    path = tmp_path / "incidents.jsonl"
    path.write_text(
        json.dumps(
            {
                "event": "fallback_started",
                "incident_id": "incident-1",
                "preceding_polls": [],
                "poll": {
                    "captured_at_local": "2026-08-18T07:00:59+02:00",
                    "captured_at_utc": "2026-08-18T05:00:59+00:00",
                    "run_id": "run-1",
                    "evaluation": {
                        "status": "fallback_active",
                        "reason": "no actionable candidate",
                    },
                    "entities": [
                        {
                            "entity_id": "sensor.goodwe_vermogen",
                            "semantic_role": "pv_power",
                            "state": "0",
                            "unit": "W",
                            "availability": "available",
                            "last_changed_at": "2026-08-18T05:00:00+00:00",
                            "last_updated_at": "2026-08-18T05:00:58+00:00",
                            "price_points": [{"large": "omitted"}],
                        }
                    ],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    overview = incident_overview(path)

    assert overview[0]["reason"] == "no actionable candidate"
    polls = overview[0]["polls"]
    assert isinstance(polls, list)
    entities = polls[0]["entities"]
    assert entities == [
        {
            "entity_id": "sensor.goodwe_vermogen",
            "semantic_role": "pv_power",
            "state": "0",
            "unit": "W",
            "availability": "available",
            "last_changed_at": "2026-08-18T05:00:00+00:00",
            "last_updated_at": "2026-08-18T05:00:58+00:00",
            "error": None,
        }
    ]


def test_diagnostic_zip_only_contains_existing_allow_list_files(tmp_path) -> None:
    incident = tmp_path / "incidents.jsonl"
    provenance = tmp_path / "provenance.json"
    missing = tmp_path / "missing.jsonl"
    incident.write_text("incident\n", encoding="utf-8")
    provenance.write_text("{}", encoding="utf-8")

    payload = diagnostic_zip((incident, missing, provenance))

    with ZipFile(BytesIO(payload)) as archive:
        assert archive.namelist() == ["incidents.jsonl", "provenance.json"]
        assert archive.read("incidents.jsonl") == b"incident\n"


def test_incident_overview_reads_only_the_bounded_file_tail(tmp_path) -> None:
    path = tmp_path / "incidents.jsonl"
    records = [
        {
            "detail_level": "basic",
            "event": "planning_outcome_changed",
            "captured_at_utc": f"2026-08-18T05:{index:02d}:00+00:00",
            "run_id": f"run-{index}",
            "evaluation_reason": f"reason-{index}",
        }
        for index in range(30)
    ]
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )

    overview = incident_overview(path)

    assert len(overview) == 20
    assert overview[0]["run_id"] == "run-10"
    assert overview[-1]["reason"] == "reason-29"
