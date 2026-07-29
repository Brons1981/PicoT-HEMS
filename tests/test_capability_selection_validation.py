from capability_selection_validation import (
    build_selection_validation_report,
    render_selection_validation_markdown,
)


def _selection_result() -> dict:
    return {
        "metadata": {"schema": "picot_hems.capability.selection"},
        "mappings": [
            {
                "capability_id": "pv.observation.power",
                "category": "pv",
                "kind": "observation",
                "status": "SELECTED",
                "selected": {
                    "entity_id": "sensor.pv_power",
                    "selection_basis": ["semantic_validation_passed"],
                },
                "candidate_count": 2,
                "eligible_candidate_count": 1,
                "candidate_audit": [
                    {
                        "entity_id": "sensor.pv_power",
                        "state": "1500",
                        "unit_of_measurement": "W",
                        "device_class": "power",
                        "platform": "solar",
                        "eligible": True,
                        "eligibility_reasons": [],
                        "semantic_validation": {
                            "status": "VALID",
                            "reasons": ["semantic_rules_satisfied"],
                        },
                        "selection_status": "SELECTED",
                        "selection_reasons": ["semantic_validation_passed"],
                    },
                    {
                        "entity_id": "sensor.pv_energy_today",
                        "state": "4.2",
                        "unit_of_measurement": "kWh",
                        "device_class": "energy",
                        "platform": "solar",
                        "eligible": False,
                        "eligibility_reasons": [
                            "semantic:energy_counter_not_instantaneous_power"
                        ],
                        "semantic_validation": {
                            "status": "REJECTED",
                            "reasons": ["energy_counter_not_instantaneous_power"],
                        },
                        "selection_status": "INELIGIBLE",
                        "selection_reasons": [
                            "semantic:energy_counter_not_instantaneous_power"
                        ],
                    },
                ],
            },
            {
                "capability_id": "grid.observation.export_power",
                "category": "grid",
                "kind": "observation",
                "status": "NO_CANDIDATE",
                "selected": None,
                "candidate_count": 0,
                "eligible_candidate_count": 0,
                "candidate_audit": [],
            },
        ],
    }


def test_report_groups_results_and_exposes_chosen_entity() -> None:
    report = build_selection_validation_report(_selection_result())

    assert [group["category"] for group in report["categories"]] == ["grid", "pv"]
    pv = next(row for row in report["results"] if row["category"] == "pv")
    assert pv["selected_entity_id"] == "sensor.pv_power"
    assert pv["candidate_count"] == 2
    assert pv["candidates"][1]["semantic_status"] == "REJECTED"


def test_expected_truth_set_records_matches_and_expected_none() -> None:
    report = build_selection_validation_report(
        _selection_result(),
        expected_mappings={
            "pv.observation.power": "sensor.pv_power",
            "grid.observation.export_power": None,
        },
    )

    statuses = {row["capability_id"]: row["expectation_status"] for row in report["results"]}
    assert statuses == {
        "grid.observation.export_power": "EXPECTED_NONE_MATCH",
        "pv.observation.power": "MATCH",
    }
    assert report["summary"]["review_passed"] is True
    assert report["summary"]["failed_review_count"] == 0


def test_mismatch_fails_review_without_changing_selection() -> None:
    source = _selection_result()
    report = build_selection_validation_report(
        source,
        expected_mappings={"pv.observation.power": "sensor.other_pv_power"},
    )

    pv = next(row for row in report["results"] if row["category"] == "pv")
    assert pv["expectation_status"] == "MISMATCH"
    assert pv["selected_entity_id"] == "sensor.pv_power"
    assert source["mappings"][0]["selected"]["entity_id"] == "sensor.pv_power"
    assert report["summary"]["review_passed"] is False
    assert report["summary"]["failed_review_count"] == 1


def test_missing_truth_entries_are_explicitly_unreviewed() -> None:
    report = build_selection_validation_report(
        _selection_result(), expected_mappings={"pv.observation.power": "sensor.pv_power"}
    )

    grid = next(row for row in report["results"] if row["category"] == "grid")
    assert grid["expectation_status"] == "NOT_REVIEWED"
    assert report["summary"]["unreviewed_capability_count"] == 1


def test_report_returns_copies_of_candidate_data() -> None:
    source = _selection_result()
    report = build_selection_validation_report(source)

    report["results"][1]["candidates"][0]["entity_id"] = "sensor.mutated"

    assert source["mappings"][0]["candidate_audit"][0]["entity_id"] == "sensor.pv_power"


def test_markdown_shows_type_capability_and_selected_entity() -> None:
    report = build_selection_validation_report(
        _selection_result(),
        expected_mappings={"pv.observation.power": "sensor.pv_power"},
    )

    markdown = render_selection_validation_markdown(report)

    assert "| Soort | Capability | Status | Gekozen entiteit | Verwacht | Controle |" in markdown
    assert "`sensor.pv_power`" in markdown
    assert "`pv.observation.power`" in markdown
    assert "sensor.pv_energy_today" in markdown
    assert "energy_counter_not_instantaneous_power" in markdown
