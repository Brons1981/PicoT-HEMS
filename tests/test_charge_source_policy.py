from picot.domain.charge_source_policy import ChargeSourcePolicy


def test_pv_only_never_permits_grid_import() -> None:
    policy = ChargeSourcePolicy.PV_ONLY

    assert policy.permits_grid_import is False
    assert policy.requires_pv_preference is True


def test_grid_supported_policy_explicitly_permits_grid_supplementation() -> None:
    policy = ChargeSourcePolicy.PV_PREFERRED_GRID_ALLOWED

    assert policy.permits_grid_import is True
    assert policy.requires_pv_preference is True


def test_policy_values_are_stable_serializable_contract_values() -> None:
    assert ChargeSourcePolicy.PV_ONLY.value == "pv_only"
    assert (
        ChargeSourcePolicy.PV_PREFERRED_GRID_ALLOWED.value
        == "pv_preferred_grid_allowed"
    )
