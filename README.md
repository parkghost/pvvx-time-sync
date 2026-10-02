<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="custom_components/pvvx_time_sync/brand/dark_logo.png">
    <img alt="pvvx BLE Time Sync" src="custom_components/pvvx_time_sync/brand/logo.png" height="96">
  </picture>
</p>

# pvvx BLE Time Sync

[![GitHub Release](https://img.shields.io/github/v/release/parkghost/pvvx-time-sync)](https://github.com/parkghost/pvvx-time-sync/releases)
[![HACS](https://img.shields.io/badge/HACS-Custom-blue.svg)](https://hacs.xyz/)
[![HA Version](https://img.shields.io/badge/HA-2026.9.0+-green.svg)](https://www.home-assistant.io/)
[![GitHub License](https://img.shields.io/github/license/parkghost/pvvx-time-sync)](https://github.com/parkghost/pvvx-time-sync/blob/main/LICENSE)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/parkghost/pvvx-time-sync)

Home Assistant integration that sets the clock of BLE thermometers running
[pvvx firmware](https://github.com/pvvx/ATC_MiThermometer) — for example the
Xiaomi MJWSD05MMC and LYWSD02MMC clocks, or LYWSD03MMC with the clock screen
enabled.

It connects through any connectable Bluetooth adapter or
[ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html)
(`active: true`), so no device-specific ESPHome configuration is needed. The
temperature and humidity readings keep coming from the built-in BTHome
integration; this integration adds a time sync device next to it.

## Features

- **Discovery**: devices advertising the default names of clock models
  (`BTH_`, `BTE_`, `D02_`) are discovered automatically. Other or renamed pvvx
  devices can be added from *Add integration → pvvx BLE Time Sync*.
- **Drift report**: before writing, each sync reads the clock and reports how
  far off it was (to the second).
- **Time write**: the new time is timed to arrive near a whole second; the
  clock ends up within about a second of Home Assistant's time.
- **Built-in schedule**: every N hours while *Auto sync* is on. Defaults to
  168 h for hardware-RTC models and 24 h for RC-oscillator clocks. The schedule
  continues from the last sync across restarts.

## Entities

| Entity | Description |
|---|---|
| `button` Sync time | Sync now |
| `switch` Auto sync | Enable the built-in schedule |
| `number` Auto sync interval | Hours between automatic syncs |
| `sensor` Last sync | Time of the last successful sync |
| `sensor` Next sync | Time of the next automatic sync or retry; unknown while *Auto sync* is off or has stopped |
| `sensor` Drift before sync | Device clock minus real time, in seconds, measured just before the last sync |

Each device gets its own device entry named after the BTHome device for the
same address (and in its area); model and firmware fill in after the first
sync.

## Installation

Requires Home Assistant 2026.9 or newer with a connectable Bluetooth adapter or
an ESPHome Bluetooth proxy with `active: true`.

### HACS (recommended)

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=parkghost&repository=pvvx-time-sync&category=integration)

1. Click the button above, or in HACS open the menu → *Custom repositories* and
   add `https://github.com/parkghost/pvvx-time-sync` with type *Integration*.
2. Download **pvvx BLE Time Sync**.
3. Restart Home Assistant.

### Manual

Copy `custom_components/pvvx_time_sync` into the `custom_components` folder of
your Home Assistant configuration and restart Home Assistant.

## Setup

[![Open your Home Assistant instance and start setting up pvvx BLE Time Sync.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=pvvx_time_sync)

Clocks with their default names (`BTH_…`, `BTE_…`, `D02_…`) show up under
*Settings → Devices & services → Discovered*. For any other pvvx device, click
the button above (or *Add integration → pvvx BLE Time Sync*) and pick it from
the list of nearby devices. Adding a device does not connect to it; the first
sync runs about 30 seconds later.

The *Sync time* button is unavailable while no connectable adapter or proxy
sees the device; the other entities keep their last values.

## Sync schedule and retries

**Schedule.** With *Auto sync* on, the next sync is due one *Auto sync
interval* after the last successful one. The time of the last sync is stored,
so a Home Assistant restart does not reset the schedule; a sync that fell due
while Home Assistant was down runs shortly after startup. Pressing *Sync time*
counts as a sync, so the schedule restarts from it. Manual and automatic syncs
never run at the same time: a press during a running sync waits for its result.

**Retries within a sync.**

- Connecting: up to 3 attempts, each through whichever adapter or proxy sees
  the device at that moment.
- Reading the device (model, current time): resent up to 3 times if the device
  does not answer within 2 seconds.
- Writing the time: never resent, since a resent value would already be stale.

**Retries after a failed sync** (only while *Auto sync* is on): after 15
minutes, then 30 minutes, 1 hour, 2 hours and so on, never longer than the
sync interval. A successful sync returns to the normal schedule. Failures raise
no notifications; *Last sync* shows when the last one succeeded, and the
*Sync time* button reports the error when pressed.

**When retrying stops.** If two syncs in a row find no pvvx firmware on the
device, automatic syncing stops and a repair issue explains why.

## Supported firmware

pvvx `ATC_MiThermometer` and `BLE_THSensor` firmware, which expose command
characteristic `0x1F1F` in service `0x1F10`. pvvx `THB2` firmware uses a
different characteristic and is not supported yet.

Connection PIN codes are not supported.

## Known limitations

- **The display can lag the clock by a few seconds.** pvvx firmware counts
  seconds while the device is awake, and it wakes once per advertising
  interval (5 seconds by default on MJWSD05MMC). A new minute therefore shows
  up to one advertising interval late, a different amount each minute. The
  clock itself stays within about a second (see *Drift before sync*). A
  shorter advertising interval, set with pvvx's TelinkMiFlasher, reduces the
  lag at the cost of battery life.
- **About one second of accuracy.** The firmware keeps whole seconds and does
  not restart its sub-second count when the time is written.

## Protocol

| Command | Request | Response (notification) |
|---|---|---|
| Device ID | `00` | `00 rev hw:u16 sw:u16 spec:u16 services:u32` |
| Get time | `23` | `23 current:u32 [last_set:u32]` |
| Set time | `23 local_seconds:u32` | same as get time |

Values are little-endian. The firmware stores **local** time; it has no time
zone setting. Writes use *write without response*.

## License

[MIT](LICENSE)
