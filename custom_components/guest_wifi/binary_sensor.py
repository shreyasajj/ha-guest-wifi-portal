"""One connectivity binary_sensor per guest device."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import GuestWifiConfigEntry
from .entity import GuestWifiEntity, track_new

ICONS = {"phone": "mdi:cellphone", "computer": "mdi:laptop", "tablet": "mdi:tablet", "other": "mdi:devices"}


async def async_setup_entry(hass: HomeAssistant, entry: GuestWifiConfigEntry, add: AddEntitiesCallback) -> None:
    coord = entry.runtime_data
    entry.async_on_unload(track_new(
        coord, add, lambda d: [x["mac"] for x in d.get("devices", [])], lambda mac: DeviceOnline(coord, mac)))


class DeviceOnline(GuestWifiEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator, mac: str) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._attr_unique_id = f"{coordinator.entry.entry_id}_device_{mac.replace(':', '')}"

    @property
    def _device(self) -> dict | None:
        return next((d for d in (self.coordinator.data or {}).get("devices", []) if d["mac"] == self._mac), None)

    @property
    def name(self) -> str:
        d = self._device
        if not d:
            return self._mac
        owner = d.get("person_name")
        return f"{owner} {d['label']}" if owner and owner.split(" ")[0] not in d["label"] else d["label"]

    @property
    def icon(self) -> str:
        d = self._device
        return ICONS.get(d["type"], "mdi:devices") if d else "mdi:devices"

    @property
    def available(self) -> bool:
        # Revoked devices disappear from the snapshot and become unavailable.
        return super().available and self._device is not None

    @property
    def is_on(self) -> bool:
        d = self._device
        return bool(d and d["online"])

    @property
    def extra_state_attributes(self) -> dict:
        d = self._device or {}
        return {k: d.get(k) for k in ("mac", "type", "nickname", "person_uid", "person_name", "current_ip",
                                       "first_seen", "last_seen", "device_id")}
