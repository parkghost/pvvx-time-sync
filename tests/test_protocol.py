"""Tests for pvvx command encoding and decoding."""

import pytest

from custom_components.pvvx_time_sync.protocol import (
    DeviceId,
    ProtocolError,
    decode_device_id,
    decode_time,
    encode_set_time,
    resolve_model,
)


def test_encode_set_time_is_little_endian() -> None:
    assert encode_set_time(0x12345678) == bytes([0x23, 0x78, 0x56, 0x34, 0x12])


def test_decode_time_rtc_model_has_no_last_set() -> None:
    reading = decode_time(bytes([0x23, 1, 0, 0, 0]))
    assert (reading.current, reading.last_set) == (1, None)


def test_decode_time_time_adjust_model_has_last_set() -> None:
    reading = decode_time(bytes([0x23, 2, 0, 0, 0, 1, 0, 0, 0]))
    assert (reading.current, reading.last_set) == (2, 1)


@pytest.mark.parametrize("data", [b"", bytes([0x23, 1]), bytes([0x33, 1, 2, 3, 4])])
def test_decode_time_rejects_other_payloads(data: bytes) -> None:
    with pytest.raises(ProtocolError):
        decode_time(data)


def test_decode_device_id() -> None:
    data = bytes([0x00, 0, 9, 0, 0x59, 0, 0, 0x0B, 0x00, 0x20, 0, 0])
    device_id = decode_device_id(data)
    assert device_id.hw_version == 9
    assert device_id.firmware == "5.9"
    assert device_id.has_hardware_clock


def test_resolve_model_fixes_lywsd02_typo() -> None:
    assert resolve_model("LYWSDO2MMC", DeviceId(49, 0x59, 0)) == "LYWSD02MMC"


def test_resolve_model_falls_back_to_device_type() -> None:
    assert resolve_model(None, DeviceId(12, 0x59, 0)) == "MJWSD05MMC_EN"
    assert resolve_model("", DeviceId(250, 0x59, 0)) == "pvvx device 250"
