from importlib import import_module


def _dashboard_html() -> str:
    return import_module("picot.v2.web_ui").DASHBOARD_HTML


def test_all_pipeline_stage_names_are_plain_dutch() -> None:
    html = _dashboard_html()

    expected_names = (
        '"Planningsinvoer"',
        '"Energiekansen"',
        '"Mogelijke plannen"',
        '"Planbeoordeling"',
        '"Uitvoeringsplan"',
        '"Uitvoering"',
        '"Uitvoerbare opdracht"',
        '"Apparaatkoppeling"',
        '"Zendure-resultaat"',
    )
    stage_names = html[
        html.index("const stageNames = [") :
        html.index("const sourceNames = {")
    ]

    assert all(name in stage_names for name in expected_names)
    for english_name in (
        '"Planning Input"',
        '"Opportunity Engine"',
        '"Candidate Engine"',
        '"Evaluation Engine"',
        '"Execution Plan Builder"',
        '"Execution Engine"',
        '"Execution Primitive"',
        '"Device Adapter"',
        '"Vendor / Result"',
    ):
        assert english_name not in stage_names


def test_dutch_result_is_visible_in_collapsed_card_summary() -> None:
    html = _dashboard_html()
    render_pipeline = html[
        html.index("function renderPipeline") :
        html.index("function renderStorageModeOverride")
    ]

    assert 'result.className = "stage-result"' in render_pipeline
    assert "result.textContent = item.result_nl" in render_pipeline
    assert "summary.append(heading, result)" in render_pipeline
    assert "details.appendChild(state)" in render_pipeline
    assert render_pipeline.index("summary.append(heading, result)") < (
        render_pipeline.index("details.appendChild(state)")
    )
    assert "summary.append(heading, state)" not in render_pipeline


def test_collapsed_pipeline_cards_use_compact_summary_spacing() -> None:
    html = _dashboard_html()

    assert ".stage-card { padding: 0; min-width: 0; }" in html
    assert ".stage-summary {" in html
    assert "padding: 10px 12px;" in html
    assert ".stage-result {" in html
    assert "font-size: 0.88rem;" in html
    assert "margin-left: 8px;" in html

