"""pvvx firmware command encoding and decoding.

Pure functions with no Home Assistant or BLE dependencies. Layouts follow
pvvx/ATC_MiThermometer ``src/cmd_parser.h`` and ``src/cmd_parser.c``.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct

CMD_DEV_ID = 0x00
CMD_UTC_TIME = 0x23

DEVICE_ID_LENGTH = 12
TIME_LENGTH = 5  # [0x23][u32 current]
TIME_WITH_LAST_SET_LENGTH = 9  # plus [u32 last_set] on time-adjust builds

SERVICE_TIME_ADJUST = 0x00001000
SERVICE_HARD_CLOCK = 0x00002000

# DEVICE_TYPE ids from app_config.h. LYWSD03MMC reports its board revision
# in hw_version instead, so the DIS model string takes precedence.
DEVICE_TYPES: dict[int, str] = {
    1: "MHO-C401",
    2: "CGG1-M",
    6: "CGDK2",
    7: "CGG1-M 2022",
    8: "MHO-C401N",
    9: "MJWSD05MMC",
    11: "MHO-C122",
    12: "MJWSD05MMC_EN",
    13: "MJWSD06MMC",
    16: "TB03F",
    17: "TS0201",
    18: "TNK01",
    22: "TH03Z",
    27: "ZTH01",
    28: "ZTH02",
    29: "PLM1",
    30: "ZTH03",
    31: "LKTMZL02",
    33: "ZTH05Z",
    37: "ZY-ZTH02",
    38: "ZY-ZTH02Pro",
    39: "ZG-227Z",
    44: "ZG-303Z",
    45: "ZBEACON-TH01",
    46: "ZB-MC",
    47: "ZBEACON-TH01 v2",
    49: "LYWSD02MMC",
    51: "ZG-204ZV",
    52: "TS0201_WING",
}

# The firmware ships this DIS model string with a letter O instead of a zero.
_MODEL_FIXUPS = {"LYWSDO2MMC": "LYWSD02MMC"}


class PvvxError(Exception):
    """Base error for pvvx device operations."""


class ProtocolError(PvvxError):
    """Raised when a device response cannot be decoded."""


@dataclass(frozen=True, slots=True)
class DeviceId:
    """Decoded response to CMD_DEV_ID."""

    hw_version: int
    sw_version: int
    services: int

    @property
    def firmware(self) -> str:
        """Firmware version, stored as BCD (0x59 -> '5.9')."""
        return f"{self.sw_version >> 4:x}.{self.sw_version & 0x0F:x}"

    @property
    def has_hardware_clock(self) -> bool:
        """True when the clock runs on an RTC chip instead of the RC oscillator."""
        return bool(self.services & SERVICE_HARD_CLOCK)


@dataclass(frozen=True, slots=True)
class TimeReading:
    """Decoded response to CMD_UTC_TIME (local-time seconds)."""

    current: int
    last_set: int | None


def encode_get_device_id() -> bytes:
    """Build the CMD_DEV_ID request."""
    return bytes([CMD_DEV_ID])


def encode_get_time() -> bytes:
    """Build a CMD_UTC_TIME read request."""
    return bytes([CMD_UTC_TIME])


def encode_set_time(local_seconds: int) -> bytes:
    """Build a CMD_UTC_TIME write. The firmware expects local time, not UTC."""
    return struct.pack("<BI", CMD_UTC_TIME, local_seconds & 0xFFFFFFFF)


def decode_device_id(data: bytes) -> DeviceId:
    """Decode ``{pid u8, rev u8, hw u16, sw u16, dev_spec u16, services u32}``."""
    if len(data) < DEVICE_ID_LENGTH or data[0] != CMD_DEV_ID:
        raise ProtocolError(f"invalid device id response: {data.hex()}")
    _, _, hw, sw, _, services = struct.unpack_from("<BBHHHI", data)
    return DeviceId(hw_version=hw, sw_version=sw, services=services)


def decode_time(data: bytes) -> TimeReading:
    """Decode ``[0x23][u32 current]`` with an optional ``[u32 last_set]``."""
    if len(data) < TIME_LENGTH or data[0] != CMD_UTC_TIME:
        raise ProtocolError(f"invalid time response: {data.hex()}")
    (current,) = struct.unpack_from("<I", data, 1)
    last_set = None
    if len(data) >= TIME_WITH_LAST_SET_LENGTH:
        (last_set,) = struct.unpack_from("<I", data, 5)
    return TimeReading(current=current, last_set=last_set)


def resolve_model(dis_model: str | None, device_id: DeviceId) -> str:
    """Pick a model name, preferring the DIS string over the device type id."""
    if dis_model:
        model = dis_model.strip("\x00 ")
        return _MODEL_FIXUPS.get(model, model)
    return DEVICE_TYPES.get(device_id.hw_version, f"pvvx device {device_id.hw_version}")
