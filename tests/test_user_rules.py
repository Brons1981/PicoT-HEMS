import json
from datetime import UTC, datetime

import pytest

from picot.v2.user_rules import UserRuleStore


def test_user_rule_store_migrates_once_and_then_remains_canonical(tmp_path) -> None:
    path = tmp_path / "user-rules.json"
    first = UserRuleStore(
        path,
        migrated_trading_soc_percent=27.0,
        now=lambda: datetime(2026, 9, 2, tzinfo=UTC),
    )
    assert first.current().maximum_trading_soc_percent == 27.0
    assert first.current().preserve_pv_during_grid_charge is True
    assert first.current().saldering_energy_tax_credit_enabled is True
    assert first.current().source == "addon_option_migration"

    changed = first.update(
        preserve_pv_during_grid_charge=False,
        maximum_trading_soc_percent=18.0,
        saldering_energy_tax_credit_enabled=False,
    )
    assert changed.revision == 2

    reloaded = UserRuleStore(path, migrated_trading_soc_percent=99.0)
    assert reloaded.current().maximum_trading_soc_percent == 18.0
    assert reloaded.current().preserve_pv_during_grid_charge is False
    assert reloaded.current().saldering_energy_tax_credit_enabled is False
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 2


@pytest.mark.parametrize("value", (-1.0, 101.0, True, "25"))
def test_user_rule_store_rejects_invalid_trading_soc(tmp_path, value) -> None:
    store = UserRuleStore(tmp_path / "rules.json", migrated_trading_soc_percent=25.0)
    with pytest.raises(ValueError):
        store.update(
            preserve_pv_during_grid_charge=True,
            maximum_trading_soc_percent=value,
        )


def test_user_rule_store_rejects_non_boolean_persisted_rule(tmp_path) -> None:
    path = tmp_path / "user-rules.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "revision": 1,
                "updated_at": "2026-09-02T08:00:00+00:00",
                "preserve_pv_during_grid_charge": "false",
                "maximum_trading_soc_percent": 25,
                "source": "strategy_dashboard",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must be boolean"):
        UserRuleStore(path, migrated_trading_soc_percent=25)
