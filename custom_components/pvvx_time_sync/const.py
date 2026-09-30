"""Constants for pvvx Time Sync."""

from datetime import timedelta

DOMAIN = "pvvx_time_sync"


# RTC clocks drift a few seconds a day; RC-oscillator clocks can drift a
# minute a day (pvvx/ATC_MiThermometer issue #56).
DEFAULT_INTERVAL_HOURS_HARDWARE_CLOCK = 168
DEFAULT_INTERVAL_HOURS_SOFTWARE_CLOCK = 24

MAX_INTERVAL_HOURS = 24 * 90

# After a failed sync, retry after 15 min, then 30 min, 1 h, ... (doubling),
# never waiting longer than the sync interval itself.
RETRY_DELAY = timedelta(minutes=15)
# Missing pvvx firmware must be seen this many times in a row before auto sync
# stops, so a stale service cache or a glitch does not end it.
NOT_PVVX_CONFIRMATIONS = 2


def default_interval_hours(*, hardware_clock: bool | None) -> int:
    """Default auto sync interval for a clock type (None: not yet known)."""
    if hardware_clock:
        return DEFAULT_INTERVAL_HOURS_HARDWARE_CLOCK
    return DEFAULT_INTERVAL_HOURS_SOFTWARE_CLOCK


# Default advertised name prefixes of pvvx firmware (ATC_MiThermometer ble.c).
# Users can rename devices, so these only pre-select candidates.
PVVX_NAME_PREFIXES = (
    "ATC_",
    "BTE_",
    "BTH_",
    "CGD_",
    "CGG_",
    "D02_",
    "MHO_",
    "MJ6_",
    "PLM_",
    "TH0_",
    "TH1-",
    "TH3_",
    "TH5_",
    "TS0_",
    "W21_",
    "ZBM-",
    "ZG2_",
    "ZG3_",
    "ZGV_",
    "ZL2_",
    "ZTH_",
    "ZY2_",
    "ZYP_",
)
# BTHome v1/v2 and pvvx custom advertising formats.
PVVX_SERVICE_DATA_UUIDS = (
    "0000fcd2-0000-1000-8000-00805f9b34fb",
    "0000181c-0000-1000-8000-00805f9b34fb",
    "0000181e-0000-1000-8000-00805f9b34fb",
    "0000181a-0000-1000-8000-00805f9b34fb",
)
