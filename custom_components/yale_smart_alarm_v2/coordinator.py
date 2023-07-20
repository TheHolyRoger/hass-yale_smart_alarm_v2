"""DataUpdateCoordinator for the Yale integration."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from yalesmartalarmclient.client import YaleSmartAlarmClient
from yalesmartalarmclient.exceptions import AuthenticationError

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LOGGER,
    YALE_BASE_ERRORS,
    YALE_EVENT_TYPE_SMOKE_ON,
    YALE_EVENT_TYPE_SMOKE_OFF,
)


class YaleDataUpdateCoordinator(DataUpdateCoordinator):
    """A Yale Data Update Coordinator."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the Yale hub."""
        self.entry = entry
        self.yale: YaleSmartAlarmClient | None = None
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    def device_on_in_updates_history(self, device, updates, enabled_type, disabled_type, minutes=3):
        update_timestamp = updates["update_timestamp"]
        accepted_timestamp = update_timestamp - timedelta(minutes=minutes)
        exists = False
        for hist_item in updates["history"]:
            hist_time = hist_item["time"]
            hist_date = datetime.strptime(hist_time, "%Y/%m/%d %H:%M:%S")
            if hist_date < accepted_timestamp:
                break
            if hist_item["type"] != device["type"]:
                continue
            if str(hist_item["area"]) != str(device["area"]):
                continue
            if str(hist_item["event_type"]) == disabled_type:
                break
            if str(hist_item["event_type"]) == enabled_type:
                exists = True
                break
        return exists

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Yale."""

        updates = await self.hass.async_add_executor_job(self.get_updates)

        locks = []
        door_windows = []
        sensors_temperature = []
        sensors_smoke = []

        for device in updates["cycle"]["device_status"]:
            state = device["status1"]
            if device["type"] == "device_type.door_lock":
                lock_status_str = device["minigw_lock_status"]
                lock_status = int(str(lock_status_str or 0), 16)
                closed = (lock_status & 16) == 16
                locked = (lock_status & 1) == 1
                if not lock_status and "device_status.lock" in state:
                    device["_state"] = "locked"
                    device["_state2"] = "unknown"
                    locks.append(device)
                    continue
                if not lock_status and "device_status.unlock" in state:
                    device["_state"] = "unlocked"
                    device["_state2"] = "unknown"
                    locks.append(device)
                    continue
                if (
                    lock_status
                    and (
                        "device_status.lock" in state or "device_status.unlock" in state
                    )
                    and closed
                    and locked
                ):
                    device["_state"] = "locked"
                    device["_state2"] = "closed"
                    locks.append(device)
                    continue
                if (
                    lock_status
                    and (
                        "device_status.lock" in state or "device_status.unlock" in state
                    )
                    and closed
                    and not locked
                ):
                    device["_state"] = "unlocked"
                    device["_state2"] = "closed"
                    locks.append(device)
                    continue
                if (
                    lock_status
                    and (
                        "device_status.lock" in state or "device_status.unlock" in state
                    )
                    and not closed
                ):
                    device["_state"] = "unlocked"
                    device["_state2"] = "open"
                    locks.append(device)
                    continue
                device["_state"] = "unavailable"
                locks.append(device)
                continue
            if device["type"] == "device_type.door_contact":
                if "device_status.dc_close" in state:
                    device["_state"] = "closed"
                    door_windows.append(device)
                    continue
                if "device_status.dc_open" in state:
                    device["_state"] = "open"
                    door_windows.append(device)
                    continue
                device["_state"] = "unavailable"
                door_windows.append(device)
                continue
            if device["type"] == "device_type.temperature_sensor":
                state = device["status_temp"]
                device["_state"] = float(state)
                sensors_temperature.append(device)
                continue
            if device["type"] == "device_type.smoke_detector":
                if self.device_on_in_updates_history(
                    device,
                    updates,
                    YALE_EVENT_TYPE_SMOKE_ON,
                    YALE_EVENT_TYPE_SMOKE_OFF,
                    minutes=3
                ):
                    state = "on"
                else:
                    state = "off"
                device["_state"] = state
                sensors_smoke.append(device)
                continue

        _door_sensor_map = {
            contact["address"]: contact["_state"] for contact in door_windows
        }
        _lock_map = {lock["address"]: lock["_state"] for lock in locks}
        _temperature_map = {s["address"]: s["_state"] for s in sensors_temperature}
        _smoke_map = {s["address"]: s["_state"] for s in sensors_smoke}

        return {
            "alarm": updates["arm_status"],
            "locks": locks,
            "door_windows": door_windows,
            "temperature_sensors": sensors_temperature,
            "smoke_sensors": sensors_smoke,
            "status": updates["status"],
            "online": updates["online"],
            "door_sensor_map": _door_sensor_map,
            "lock_map": _lock_map,
            "temperature_map": _temperature_map,
            "smoke_map": _smoke_map,
            "panel_info": updates["panel_info"],
        }

    def get_updates(self) -> dict[str, Any]:
        """Fetch data from Yale."""

        if self.yale is None:
            try:
                self.yale = YaleSmartAlarmClient(
                    self.entry.data[CONF_USERNAME], self.entry.data[CONF_PASSWORD]
                )
            except AuthenticationError as error:
                raise ConfigEntryAuthFailed from error
            except YALE_BASE_ERRORS as error:
                raise UpdateFailed from error

        try:
            arm_status = self.yale.get_armed_status()
            data = self.yale.get_all()
            cycle = data["CYCLE"]
            history = data["HISTORY"]
            status = data["STATUS"]
            online = data["ONLINE"]
            panel_info = data["PANEL INFO"]
            token_time = data["AUTH CHECK"]["token_time"]
            update_timestamp = datetime.strptime(token_time, "%Y-%m-%d %H:%M:%S")

        except AuthenticationError as error:
            raise ConfigEntryAuthFailed from error
        except YALE_BASE_ERRORS as error:
            raise UpdateFailed from error

        return {
            "arm_status": arm_status,
            "cycle": cycle,
            "status": status,
            "online": online,
            "panel_info": panel_info,
            "history": history,
            "update_timestamp": update_timestamp,
        }
