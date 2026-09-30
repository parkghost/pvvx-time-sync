"""A fake pvvx device speaking the command protocol over a GattClient."""

from __future__ import annotations

from collections.abc import Callable
import struct

from bleak.exc import BleakCharacteristicNotFoundError

from custom_components.pvvx_time_sync.client import (
    CMD_CHAR_UUID,
    FIRMWARE_REVISION_UUID,
    MODEL_NUMBER_UUID,
)


class FakeClock:
    """Local wall clock that advances only when told to (or on sleep)."""

    def __init__(self, start: float) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakePvvxDevice:
    """Answers 0x00 and 0x23 like ATC_MiThermometer firmware."""

    def __init__(
        self,
        clock: FakeClock,
        *,
        device_time: int = 0,
        firmware: bytes = b"github.com/pvvx",
        model: bytes | None = b"MJWSD05MMC",
        hw_version: int = 9,
        services: int = 0x2000,
        latency: float = 0.05,
        has_command_char: bool = True,
        noise: bytes | None = None,
        ignore_set_time: bool = False,
        drop_writes: int = 0,
        notify_error: Exception | None = None,
    ) -> None:
        self.clock = clock
        self.device_time = device_time
        self.firmware = firmware
        self.model = model
        self.hw_version = hw_version
        self.services = services
        self.latency = latency
        self.has_command_char = has_command_char
        self.noise = noise
        self.ignore_set_time = ignore_set_time
        self.drop_writes = drop_writes
        self.notify_error = notify_error
        self.cache_cleared = False
        self.writes: list[tuple[float, bytes, bool | None]] = []
        self.connected = False
        self._callback: Callable | None = None

    async def connect(self) -> FakePvvxDevice:
        self.connected = True
        return self

    async def start_notify(self, char_specifier: str, callback: Callable) -> None:
        if self.notify_error:
            raise self.notify_error
        if not self.has_command_char:
            raise BleakCharacteristicNotFoundError(char_specifier)
        self._callback = callback

    async def read_gatt_char(self, char_specifier: str) -> bytearray:
        value = {
            FIRMWARE_REVISION_UUID: self.firmware,
            MODEL_NUMBER_UUID: self.model,
        }.get(char_specifier)
        if value is None:
            raise BleakCharacteristicNotFoundError(char_specifier)
        return bytearray(value)

    async def write_gatt_char(
        self, char_specifier: str, data: bytes, response: bool | None = None
    ) -> None:
        assert char_specifier == CMD_CHAR_UUID
        self.clock.now += self.latency
        self.writes.append((self.clock.now, bytes(data), response))
        assert self._callback is not None
        if self.drop_writes:
            # Mimics writes lost right after connecting.
            self.drop_writes -= 1
            return
        if self.noise:
            self._callback(None, bytearray(self.noise))
        cmd = data[0]
        if cmd == 0x00:
            reply = struct.pack(
                "<BBHHHI", 0x00, 0, self.hw_version, 0x59, 0x0B00, self.services
            )
        elif cmd == 0x23:
            if len(data) >= 5 and not self.ignore_set_time:
                (self.device_time,) = struct.unpack_from("<I", data, 1)
            reply = struct.pack("<BI", 0x23, self.device_time)
        else:
            raise AssertionError(f"unexpected command {data.hex()}")
        self.clock.now += self.latency
        self._callback(None, bytearray(reply))

    async def clear_cache(self) -> bool:
        self.cache_cleared = True
        return True

    async def disconnect(self) -> None:
        self.connected = False
