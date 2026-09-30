"""BLE client for pvvx firmware devices.

The client does not know about Home Assistant: how a connection is opened and
what the local wall clock reads are injected, so the protocol flow can be
tested with fakes.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging
import math
from types import TracebackType
from typing import Protocol, Self

from bleak.exc import BleakCharacteristicNotFoundError

from .protocol import (
    CMD_DEV_ID,
    CMD_UTC_TIME,
    PvvxError,
    decode_device_id,
    decode_time,
    encode_get_device_id,
    encode_get_time,
    encode_set_time,
    resolve_model,
)

_LOGGER = logging.getLogger(__name__)

CMD_CHAR_UUID = "00001f1f-0000-1000-8000-00805f9b34fb"
MODEL_NUMBER_UUID = "00002a24-0000-1000-8000-00805f9b34fb"
FIRMWARE_REVISION_UUID = "00002a26-0000-1000-8000-00805f9b34fb"
PVVX_FIRMWARE_SIGNATURE = "github.com/pvvx"

# A write sent right after connecting can be dropped, so idempotent commands
# are resent when no answer arrives in time.
RESPONSE_TIMEOUT = 2.0
REQUEST_ATTEMPTS = 3
# The device clock has one-second resolution; a confirmation within this many
# seconds of the written value counts as a successful write.
CONFIRM_TOLERANCE = 1


class NotPvvxDeviceError(PvvxError):
    """The device does not run pvvx firmware with the command characteristic."""


class NoResponseError(PvvxError):
    """The device did not answer a command."""


class SyncVerificationError(PvvxError):
    """The device did not report the time that was written."""


class GattClient(Protocol):
    """The subset of BleakClient this module relies on."""

    async def start_notify(self, char_specifier: str, callback: Callable) -> None:
        """Subscribe to notifications of a characteristic."""
        ...

    async def write_gatt_char(
        self,
        char_specifier: str,
        data: bytes,
        response: bool | None = None,  # noqa: FBT001 - mirrors BleakClient
    ) -> None:
        """Write to a characteristic."""
        ...

    async def read_gatt_char(self, char_specifier: str) -> bytearray:
        """Read a characteristic."""
        ...

    async def disconnect(self) -> None:
        """Close the connection."""
        ...


type ConnectFn = Callable[[], Awaitable[GattClient]]
type LocalClockFn = Callable[[], float]
type SleepFn = Callable[[float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class DeviceDetails:
    """What the device reports about itself."""

    model: str
    firmware: str
    has_hardware_clock: bool


@dataclass(frozen=True, slots=True)
class SyncResult:
    """Outcome of a successful time sync."""

    details: DeviceDetails
    drift_seconds: int
    written_local_seconds: int


class _Session:
    """One connection with notifications on the command characteristic."""

    def __init__(
        self, connect: ConnectFn, local_clock: LocalClockFn, name: str
    ) -> None:
        self._connect = connect
        self._local_clock = local_clock
        self._name = name
        self._client: GattClient | None = None
        self._responses: asyncio.Queue[bytes] = asyncio.Queue()
        # Local-clock send and receive times of the last answered attempt.
        self.last_exchange: tuple[float, float] = (0.0, 0.0)

    async def __aenter__(self) -> Self:
        _LOGGER.debug("%s: connecting", self._name)
        self._client = await self._connect()
        _LOGGER.debug("%s: connected", self._name)
        try:
            await self._client.start_notify(CMD_CHAR_UUID, self._on_notify)
        except BleakCharacteristicNotFoundError as err:
            _LOGGER.debug(
                "%s: command characteristic missing; clearing service cache",
                self._name,
            )
            # A stale service cache looks the same, so refresh it for next time.
            if clear_cache := getattr(self._client, "clear_cache", None):
                await clear_cache()
            await self._client.disconnect()
            raise NotPvvxDeviceError(
                f"command characteristic unavailable: {err}"
            ) from err
        except BaseException:
            await self._client.disconnect()
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        assert self._client is not None
        await self._client.disconnect()
        _LOGGER.debug("%s: disconnected", self._name)

    def _on_notify(self, _sender: object, data: bytearray) -> None:
        self._responses.put_nowait(bytes(data))

    async def read(self, uuid: str) -> str | None:
        """Read a string characteristic, or None when it is missing."""
        assert self._client is not None
        try:
            raw = await self._client.read_gatt_char(uuid)
        except BleakCharacteristicNotFoundError:
            _LOGGER.debug("%s: characteristic %s missing", self._name, uuid)
            return None
        value = bytes(raw).decode("utf-8", errors="replace").strip("\x00 ")
        _LOGGER.debug("%s: read %s = %r", self._name, uuid, value)
        return value

    async def request(
        self, payload: bytes, cmd: int, attempts: int = REQUEST_ATTEMPTS
    ) -> bytes:
        """Send a command and wait for the notification that answers it.

        Only pass ``attempts > 1`` for commands that are safe to resend.
        """
        assert self._client is not None
        for attempt in range(1, attempts + 1):
            while not self._responses.empty():
                self._responses.get_nowait()
            sent_at = self._local_clock()
            _LOGGER.debug(
                "%s: -> %s (attempt %d/%d)",
                self._name,
                payload.hex(),
                attempt,
                attempts,
            )
            await self._client.write_gatt_char(CMD_CHAR_UUID, payload, response=False)
            try:
                async with asyncio.timeout(RESPONSE_TIMEOUT):
                    data = await self._next_response(cmd)
            except TimeoutError:
                _LOGGER.debug(
                    "%s: no answer to 0x%02x within %ss",
                    self._name,
                    cmd,
                    RESPONSE_TIMEOUT,
                )
                continue
            self.last_exchange = (sent_at, self._local_clock())
            _LOGGER.debug(
                "%s: <- %s after %.0f ms",
                self._name,
                data.hex(),
                (self.last_exchange[1] - sent_at) * 1000,
            )
            return data
        raise NoResponseError(
            f"no response to command 0x{cmd:02x} after {attempts} attempt(s)"
        )

    async def _next_response(self, cmd: int) -> bytes:
        while True:
            data = await self._responses.get()
            # The device may stream unrelated notifications (measurements).
            if data and data[0] == cmd:
                return data
            _LOGGER.debug("%s: ignored notification %s", self._name, data.hex())


class PvvxClient:
    """Sets the clock of pvvx devices."""

    def __init__(
        self,
        connect: ConnectFn,
        local_clock: LocalClockFn,
        sleep: SleepFn = asyncio.sleep,
        *,
        name: str = "pvvx",
    ) -> None:
        """Use ``connect`` for each session and ``local_clock`` as the time source.

        ``name`` prefixes the debug log lines of this device.
        """
        self._name = name
        self._connect = connect
        self._local_clock = local_clock
        self._sleep = sleep

    async def sync_time(self) -> SyncResult:
        """Confirm the device runs pvvx firmware, then set its clock.

        Everything happens over one connection: checking the firmware costs a
        couple of reads, far less than connecting a second time.
        """
        async with _Session(self._connect, self._local_clock, self._name) as session:
            details = await self._identify(session)
            drift, one_way = await self._measure_drift(session)
            target = await self._write_time(session, one_way)
        return SyncResult(
            details=details, drift_seconds=drift, written_local_seconds=target
        )

    async def _identify(self, session: _Session) -> DeviceDetails:
        firmware_string = await session.read(FIRMWARE_REVISION_UUID)
        if not firmware_string or PVVX_FIRMWARE_SIGNATURE not in firmware_string:
            raise NotPvvxDeviceError(f"unexpected firmware: {firmware_string!r}")
        dis_model = await session.read(MODEL_NUMBER_UUID)
        device_id = decode_device_id(
            await session.request(encode_get_device_id(), CMD_DEV_ID)
        )
        details = DeviceDetails(
            model=resolve_model(dis_model, device_id),
            firmware=device_id.firmware,
            has_hardware_clock=device_id.has_hardware_clock,
        )
        _LOGGER.debug(
            "%s: %s, firmware %s, %s clock, services 0x%08x",
            self._name,
            details.model,
            details.firmware,
            "hardware" if details.has_hardware_clock else "software",
            device_id.services,
        )
        return details

    async def _measure_drift(self, session: _Session) -> tuple[int, float]:
        """Read the device clock; return (drift in seconds, one-way link delay).

        Drift is device minus local time, accurate to a second. The link delay
        is estimated as half the round trip of this read.
        """
        reading = decode_time(await session.request(encode_get_time(), CMD_UTC_TIME))
        sent_at, received_at = session.last_exchange
        one_way = (received_at - sent_at) / 2
        local = math.floor(received_at - one_way)
        drift = reading.current - local
        _LOGGER.debug(
            "%s: device %d, local %d, drift %+ds, link delay %.0f ms",
            self._name,
            reading.current,
            local,
            drift,
            one_way * 1000,
        )
        return drift, one_way

    async def _write_time(self, session: _Session, one_way: float) -> int:
        """Write the local time, timed to arrive near a whole second.

        The firmware keeps whole seconds, so expect about one second of
        accuracy. Returns the written value.
        """
        now = self._local_clock()
        target = math.floor(now + one_way) + 1
        wait = max(0.0, target - one_way - now)
        _LOGGER.debug("%s: writing %d in %.0f ms", self._name, target, wait * 1000)
        await self._sleep(wait)
        # Not resent: a retried write would carry a stale timestamp.
        confirmed = decode_time(
            await session.request(encode_set_time(target), CMD_UTC_TIME, attempts=1)
        )
        _LOGGER.debug("%s: device confirms %d", self._name, confirmed.current)
        if abs(confirmed.current - target) > CONFIRM_TOLERANCE:
            raise SyncVerificationError(
                f"wrote {target}, device reports {confirmed.current}"
            )
        return target
