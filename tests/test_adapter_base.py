"""DeviceAdapter Protocol is satisfied by FakeAdapter (used in daemon tests)
and would be satisfied by any class implementing the four methods."""

from claude_beacon.adapters.base import DeviceAdapter, DeviceError


def test_device_error_is_exception():
    assert issubclass(DeviceError, Exception)


def test_protocol_runtime_checkable_with_fake(fake_adapter):
    assert isinstance(fake_adapter, DeviceAdapter)


def test_protocol_rejects_non_conforming_class():
    class NotEnough:
        name = "broken"
        # missing connect/apply_state/health_check/close

    assert not isinstance(NotEnough(), DeviceAdapter)
