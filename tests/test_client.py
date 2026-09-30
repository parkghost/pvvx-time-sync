"""Tests for the pvvx BLE client protocol flow."""

from bleak.exc import BleakError
import pytest

from custom_components.pvvx_time_sync import client as client_module
from custom_components.pvvx_time_sync.client import (
    NoResponseError,
    NotPvvxDeviceError,
    PvvxClient,
    SyncVerificationError,
)

from .fakes import FakeClock, FakePvvxDevice

START = 1_790_000_000.3


@pytest.fixture(autouse=True)
def fast_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "RESPONSE_TIMEOUT", 0.01)


def make_client(device: FakePvvxDevice, clock: FakeClock) -> PvvxClient:
    return PvvxClient(device.connect, clock, clock.sleep)


async def test_sync_reports_device_details() -> None:
    clock = FakeClock(START)
    device = FakePvvxDevice(clock, device_time=int(START))
    details = (await make_client(device, clock).sync_time()).details
    assert details.model == "MJWSD05MMC"
    assert details.firmware == "5.9"
    assert details.has_hardware_clock
    assert not device.connected


async def test_sync_rejects_other_firmware_before_writing() -> None:
    clock = FakeClock(START)
    device = FakePvvxDevice(clock, firmware=b"atc1441")
    with pytest.raises(NotPvvxDeviceError):
        await make_client(device, clock).sync_time()
    assert device.writes == []
    assert not device.connected


async def test_sync_rejects_missing_command_characteristic() -> None:
    clock = FakeClock(START)
    device = FakePvvxDevice(clock, has_command_char=False)
    with pytest.raises(NotPvvxDeviceError):
        await make_client(device, clock).sync_time()
    # The service cache may be stale; the next attempt rediscovers services.
    assert device.cache_cleared
    assert not device.connected


async def test_sync_link_errors_are_not_mistaken_for_other_firmware() -> None:
    clock = FakeClock(START)
    device = FakePvvxDevice(clock, notify_error=BleakError("proxy disconnected"))
    with pytest.raises(BleakError, match="proxy disconnected"):
        await make_client(device, clock).sync_time()
    assert not device.cache_cleared
    assert not device.connected


async def test_sync_without_model_string_falls_back_to_device_type() -> None:
    clock = FakeClock(START)
    device = FakePvvxDevice(clock, device_time=int(START), model=None, hw_version=49)
    details = (await make_client(device, clock).sync_time()).details
    assert details.model == "LYWSD02MMC"


async def test_sync_reports_drift_and_writes_on_second_boundary() -> None:
    clock = FakeClock(START)
    device = FakePvvxDevice(clock, device_time=int(START) + 7, latency=0.05)

    result = await make_client(device, clock).sync_time()

    assert result.drift_seconds == 7
    written_at, payload, response = device.writes[-1]
    assert response is False
    assert payload[0] == 0x23
    assert device.device_time == result.written_local_seconds
    # The write lands on the device exactly as the host enters that second.
    assert written_at == pytest.approx(result.written_local_seconds)


async def test_sync_ignores_unrelated_notifications() -> None:
    clock = FakeClock(START)
    device = FakePvvxDevice(clock, device_time=int(START), noise=b"\x33\x01\x02")
    result = await make_client(device, clock).sync_time()
    assert result.drift_seconds == 0


async def test_sync_resends_commands_dropped_after_connecting() -> None:
    clock = FakeClock(START)
    device = FakePvvxDevice(clock, device_time=int(START), drop_writes=2)
    result = await make_client(device, clock).sync_time()
    assert result.drift_seconds == 0
    # Two dropped device-id requests, then device id, get time and set time.
    assert [w[1][0] for w in device.writes] == [0x00, 0x00, 0x00, 0x23, 0x23]


async def test_sync_gives_up_when_device_never_answers() -> None:
    clock = FakeClock(START)
    device = FakePvvxDevice(clock, drop_writes=99)
    with pytest.raises(NoResponseError, match="0x00 after 3"):
        await make_client(device, clock).sync_time()
    assert not device.connected


async def test_sync_fails_when_device_keeps_old_time() -> None:
    clock = FakeClock(START)
    device = FakePvvxDevice(clock, device_time=100, ignore_set_time=True)
    with pytest.raises(SyncVerificationError):
        await make_client(device, clock).sync_time()
    assert not device.connected
