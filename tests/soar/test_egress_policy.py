import pytest


def test_parse_empty_config_denies_private_allows_public():
    from soar.egress_policy import parse

    policy = parse({})
    assert policy.is_allowed("192.168.1.51") is False
    assert policy.is_allowed("8.8.8.8") is True


def test_parse_allow_cidr_permits_matching_private_address():
    from soar.egress_policy import parse

    policy = parse({"allow": ["192.168.1.0/24"]})
    assert policy.is_allowed("192.168.1.51") is True
    assert policy.is_allowed("10.0.0.1") is False


def test_parse_observe_mode_allows_everything():
    from soar.egress_policy import parse

    policy = parse({"mode": "observe"})
    assert policy.is_allowed("192.168.1.51") is True
    assert policy.is_allowed("10.0.0.1") is True
    assert policy.is_allowed("8.8.8.8") is True


def test_parse_invalid_cidr_raises():
    from soar.egress_policy import parse

    with pytest.raises(ValueError):
        parse({"allow": ["не-cidr"]})


def test_parse_invalid_mode_raises():
    from soar.egress_policy import parse

    with pytest.raises(ValueError):
        parse({"mode": "чушь"})


def test_parse_allow_accepts_single_ip_without_mask():
    from soar.egress_policy import parse

    policy = parse({"allow": ["192.168.1.51"]})
    assert policy.is_allowed("192.168.1.51") is True
    assert policy.is_allowed("192.168.1.52") is False
