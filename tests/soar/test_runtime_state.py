from soar import runtime_state


def test_dry_run_round_trip():
    runtime_state.set_dry_run(False)
    assert runtime_state.is_dry_run() is False
    runtime_state.set_dry_run(True)
    assert runtime_state.is_dry_run() is True
    runtime_state.set_dry_run(False)
    assert runtime_state.is_dry_run() is False
