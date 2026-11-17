import json

import pytest

from picot.v2.user_rules import UserRuleStore


@pytest.mark.parametrize('ceiling,expected', [(37.5, (0, 12.5, 25, 37.5)),
                                            (50, (0, 50 / 3, 100 / 3, 50))])
def test_strategy_maps_separate_ceiling_without_changing_other_rules(tmp_path, ceiling, expected):
    store = UserRuleStore(tmp_path / 'rules.json', migrated_trading_soc_percent=25)
    before = store.update(preserve_pv_during_grid_charge=True, maximum_trading_soc_percent=25,
                          market_minimum_spread_eur_per_kwh=.05, market_wear_eur_per_kwh=.025)
    for position, maximum in enumerate(expected):
        profile = store.update(strategy_position=position, strategy_trade_ceiling_percent=ceiling)
        assert profile.maximum_trading_soc_percent == pytest.approx(maximum)
        assert profile.market_wear_eur_per_kwh == before.market_wear_eur_per_kwh
        assert profile.market_minimum_spread_eur_per_kwh == before.market_minimum_spread_eur_per_kwh
        assert profile.preserve_pv_during_grid_charge == before.preserve_pv_during_grid_charge
        assert (profile.saldering_energy_tax_credit_enabled
                == before.saldering_energy_tax_credit_enabled)
        rule = profile.market_rule()
        assert (rule is None) == (position == 0)
        if rule is not None:
            assert rule.capacity_fraction == pytest.approx(maximum / 100)
        public = profile.as_public_dict()
        assert public['strategy_position'] == position
        assert public['strategy_trade_ceiling_percent'] == ceiling
        assert public['strategy_mapping']['effective_trading_soc_percent'] == pytest.approx(maximum)
        restored = UserRuleStore(tmp_path / 'rules.json', migrated_trading_soc_percent=99)
        assert restored.current() == profile


@pytest.mark.parametrize('legacy,position,ceiling', [(25, 2, 37.5), (0, 2, 0), (100, 3, 100)])
def test_migration_preserves_existing_effective_maximum(tmp_path, legacy, position, ceiling):
    store = UserRuleStore(tmp_path / 'rules.json', migrated_trading_soc_percent=legacy)
    assert store.current().maximum_trading_soc_percent == legacy
    assert store.current().as_public_dict()['strategy_position'] == position
    assert store.current().as_public_dict()['strategy_trade_ceiling_percent'] == ceiling
    changed = store.update(market_wear_eur_per_kwh=.02)
    assert changed.maximum_trading_soc_percent == legacy


@pytest.mark.parametrize('payload', [dict(strategy_position=v)
                                    for v in (4, -1, True, 1.5, '2', None)]
                         + [dict(strategy_trade_ceiling_percent=v)
                            for v in (-1, 101, True, float('nan'), float('inf'), '50', None)])
def test_invalid_or_unimplemented_strategy_cannot_mutate_state(tmp_path, payload):
    path = tmp_path / 'rules.json'
    store = UserRuleStore(path, migrated_trading_soc_percent=25)
    before, persisted = store.current(), path.read_bytes()
    with pytest.raises(ValueError):
        store.update(**payload)
    assert store.current() == before
    assert path.read_bytes() == persisted


def test_zero_disables_trade_without_forgetting_ceiling_and_legacy_stays_effective(tmp_path):
    path = tmp_path / 'rules.json'
    store = UserRuleStore(path, migrated_trading_soc_percent=25)
    store.update(strategy_trade_ceiling_percent=50, strategy_position=0)
    restored = UserRuleStore(path, migrated_trading_soc_percent=99)
    assert restored.current().market_rule() is None
    assert json.loads(path.read_text())['maximum_trading_soc_percent'] == 0
    enabled = restored.update(strategy_position=2)
    assert enabled.maximum_trading_soc_percent == pytest.approx(100 / 3)
    assert enabled.as_public_dict()['strategy_trade_ceiling_percent'] == 50


def test_old_client_maximum_remains_exact_and_does_not_double_scale(tmp_path):
    store = UserRuleStore(tmp_path / 'rules.json', migrated_trading_soc_percent=25)
    store.update(strategy_position=1, strategy_trade_ceiling_percent=37.5)
    same = store.update(maximum_trading_soc_percent=12.5)
    assert same.as_public_dict()['strategy_position'] == 1
    assert same.as_public_dict()['strategy_trade_ceiling_percent'] == 37.5
    changed = store.update(maximum_trading_soc_percent=50)
    assert changed.maximum_trading_soc_percent == 50
    assert changed.as_public_dict()['strategy_trade_ceiling_percent'] == 75


def test_conflicting_old_and_new_parameters_are_rejected(tmp_path):
    store = UserRuleStore(tmp_path / 'rules.json', migrated_trading_soc_percent=25)
    with pytest.raises(ValueError):
        store.update(maximum_trading_soc_percent=25, strategy_position=0)
