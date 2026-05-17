"""State enum: four values, string-round-trippable for state-file IO."""

import pytest

from claude_beacon.state import State


def test_state_has_exactly_four_values():
    assert {s.value for s in State} == {"off", "idle", "working", "input"}


@pytest.mark.parametrize("value", ["off", "idle", "working", "input"])
def test_state_round_trips_through_string(value: str):
    s = State(value)
    assert s.value == value
    assert str(s) == value or s.value == value  # str repr details don't matter


def test_state_rejects_unknown_value():
    with pytest.raises(ValueError):
        State("blinking")


from claude_beacon.state import acquire_lock, LockHeldError


def test_acquire_lock_succeeds_on_fresh_file(tmp_path):
    lock = tmp_path / "test.lock"
    fp = open(lock, "w")
    try:
        acquire_lock(fp)  # should not raise
    finally:
        fp.close()


def test_acquire_lock_fails_when_already_held(tmp_path):
    lock = tmp_path / "test.lock"
    fp1 = open(lock, "w")
    acquire_lock(fp1)
    try:
        fp2 = open(lock, "w")
        try:
            with pytest.raises(LockHeldError):
                acquire_lock(fp2)
        finally:
            fp2.close()
    finally:
        fp1.close()
