import pytest


@pytest.fixture(autouse=True)
def _reset_policy():
    import soar.tools._net as net
    from soar.egress_policy import parse

    original = net._policy
    yield
    net._policy = original if original is not None else parse({})


def test_validate_external_url_allows_private_address_in_policy():
    import soar.tools._net as net
    from soar.egress_policy import parse

    net.set_policy(parse({"allow": ["192.168.1.0/24"]}))
    net._validate_external_url("http://192.168.1.51/")  # must not raise


def test_validate_external_url_still_blocks_address_outside_allowlist():
    import soar.tools._net as net
    from soar.egress_policy import parse

    net.set_policy(parse({"allow": ["192.168.1.0/24"]}))
    with pytest.raises(ValueError):
        net._validate_external_url("http://10.0.0.1/")


def test_validate_external_url_default_policy_blocks_private():
    import soar.tools._net as net
    from soar.egress_policy import parse

    net.set_policy(parse({}))
    with pytest.raises(ValueError):
        net._validate_external_url("http://192.168.1.51/")
