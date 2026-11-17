import json
from datetime import UTC, datetime

import pytest

from picot.v2.user_rules import UserRuleStore


def test_wear_migrates_existing_option_once_and_keeps_fractional_maximum(tmp_path):
    path = tmp_path / "rules.json"
    store = UserRuleStore(path, migrated_trading_soc_percent=25, migrated_wear_eur_per_kwh=0.03)
    assert store.current().market_wear_eur_per_kwh == 0.03
    profile = store.update(preserve_pv_during_grid_charge=True,
                           maximum_trading_soc_percent=37.5, market_wear_eur_per_kwh=0.025)
    restored = UserRuleStore(path, migrated_trading_soc_percent=50, migrated_wear_eur_per_kwh=.09)
    assert restored.current() == profile
    assert profile.maximum_trading_soc_percent == 37.5
    assert profile.as_public_dict()["market_wear_eur_per_kwh"] == .025
    preserved = restored.update(preserve_pv_during_grid_charge=False,
                               maximum_trading_soc_percent=37.5)
    assert preserved.market_wear_eur_per_kwh == .025
    assert json.loads(path.read_text())["schema_version"] == 2  # dev339 can still read it


def test_old_profile_gains_wear_from_existing_option(tmp_path):
    path = tmp_path / "rules.json"
    store = UserRuleStore(path, migrated_trading_soc_percent=25)
    old = store.current().as_public_dict()
    old.pop("market_wear_eur_per_kwh", None)
    path.write_text(json.dumps(old))
    restored = UserRuleStore(path, migrated_trading_soc_percent=50, migrated_wear_eur_per_kwh=.04)
    assert restored.current().market_wear_eur_per_kwh == .04
    assert restored.current().maximum_trading_soc_percent == 25


@pytest.mark.parametrize("value", [-.01, float("nan"), float("inf"), True, "0.05", None, 1.01])
def test_invalid_wear_does_not_change_rules(tmp_path, value):
    store = UserRuleStore(tmp_path / "rules.json", migrated_trading_soc_percent=25,
                          now=lambda: datetime(2026, 11, 15, tzinfo=UTC))
    before = store.current()
    with pytest.raises(ValueError):
        store.update(preserve_pv_during_grid_charge=True, maximum_trading_soc_percent=25,
                     market_wear_eur_per_kwh=value)
    assert store.current() == before


def test_zero_wear_and_zero_maximum_are_valid(tmp_path):
    store = UserRuleStore(tmp_path / "rules.json", migrated_trading_soc_percent=25)
    profile = store.update(preserve_pv_during_grid_charge=True, maximum_trading_soc_percent=0,
                           market_wear_eur_per_kwh=0)
    assert profile.market_rule() is None
    assert profile.market_wear_eur_per_kwh == 0


def test_bonus_anchor_is_server_owned_and_unrelated_edits_do_not_reset_it(tmp_path):
    now = datetime(2026, 11, 15, 9, tzinfo=UTC)
    store = UserRuleStore(tmp_path / "rules.json", migrated_trading_soc_percent=25, now=lambda: now)
    raw = dict(enabled=True, latitude=51.6, longitude=4.6, annual_exported_kwh=1300)
    profile = store.update(preserve_pv_during_grid_charge=True, maximum_trading_soc_percent=37.5,
                           solar_export_bonus=raw)
    assert profile.solar_export_bonus.annual_exported_at == now
    assert profile.solar_export_bonus.effective_from == now
    now = datetime(2026, 11, 15, 10, tzinfo=UTC)
    same = store.update(preserve_pv_during_grid_charge=True, maximum_trading_soc_percent=25,
                        solar_export_bonus=raw)
    assert same.solar_export_bonus == profile.solar_export_bonus
    confirmed = store.update(preserve_pv_during_grid_charge=True, maximum_trading_soc_percent=25,
                             solar_export_bonus=dict(raw, confirm_annual_export=True))
    assert confirmed.solar_export_bonus.annual_exported_at == now
    restored = UserRuleStore(tmp_path / "rules.json", migrated_trading_soc_percent=0)
    assert restored.current() == confirmed


def test_bonus_unknown_annual_usage_is_not_zero(tmp_path):
    store = UserRuleStore(tmp_path / "rules.json", migrated_trading_soc_percent=25)
    profile = store.update(preserve_pv_during_grid_charge=True, maximum_trading_soc_percent=25,
                           solar_export_bonus=dict(enabled=True, latitude=51.6, longitude=4.6,
                                                   annual_exported_kwh=None))
    assert profile.solar_export_bonus.annual_exported_kwh is None
    assert profile.solar_export_bonus.annual_exported_at is None


def test_new_year_save_does_not_relabel_last_year_export_as_current_year(tmp_path):
    now = datetime(2026, 12, 31, 9, tzinfo=UTC)
    store = UserRuleStore(tmp_path / "rules.json", migrated_trading_soc_percent=25, now=lambda: now)
    raw = dict(enabled=True, latitude=51.6, longitude=4.6, annual_exported_kwh=6400)
    old = store.update(preserve_pv_during_grid_charge=True, maximum_trading_soc_percent=25,
                       solar_export_bonus=raw)
    now = datetime(2027, 1, 1, 9, tzinfo=UTC)
    changed = store.update(preserve_pv_during_grid_charge=True, maximum_trading_soc_percent=37.5,
                           market_wear_eur_per_kwh=.025, solar_export_bonus=raw)
    assert changed.solar_export_bonus == old.solar_export_bonus


@pytest.mark.parametrize("changes", [dict(latitude=None), dict(longitude=True),
                                     dict(annual_exported_kwh=True), dict(latitude=float("nan")),
                                     dict(enabled="true"), dict(annual_exported_kwh=-1)])
def test_invalid_bonus_never_overwrites_valid_profile(tmp_path, changes):
    store = UserRuleStore(tmp_path / "rules.json", migrated_trading_soc_percent=25)
    before = store.current()
    raw = dict(enabled=True, latitude=51.6, longitude=4.6, annual_exported_kwh=1300)
    with pytest.raises(ValueError):
        store.update(preserve_pv_during_grid_charge=True, maximum_trading_soc_percent=25,
                     solar_export_bonus=raw | changes)
    assert store.current() == before
