"""One device_tracker per person, driven by their tracked phone."""
from __future__ import annotations

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.const import STATE_HOME, STATE_NOT_HOME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import GuestWifiConfigEntry
from .entity import GuestWifiEntity, track_new


async def async_setup_entry(hass: HomeAssistant, entry: GuestWifiConfigEntry, add: AddEntitiesCallback) -> None:
    coord = entry.runtime_data
    entry.async_on_unload(track_new(
        coord, add, lambda d: [p["person_uid"] for p in d.get("people", [])],
        lambda uid: PersonTracker(coord, uid)))


class PersonTracker(GuestWifiEntity, TrackerEntity):
    """Home when the person's tracked phone is on the guest network."""

    _attr_icon = "mdi:account-wifi"

    def __init__(self, coordinator, person_uid: str) -> None:
        super().__init__(coordinator)
        self._uid = person_uid
        self._attr_unique_id = f"{coordinator.entry.entry_id}_person_{person_uid}"

    @property
    def _person(self) -> dict | None:
        return next((p for p in (self.coordinator.data or {}).get("people", []) if p["person_uid"] == self._uid), None)

    @property
    def name(self) -> str:
        p = self._person
        return p["name"] if p else self._uid

    @property
    def available(self) -> bool:
        return super().available and self._person is not None

    @property
    def source_type(self) -> SourceType:
        return SourceType.ROUTER

    @property
    def location_name(self) -> str:
        p = self._person
        return STATE_HOME if p and p["home"] and not p["blocked"] else STATE_NOT_HOME

    @property
    def latitude(self) -> float | None:
        return None

    @property
    def longitude(self) -> float | None:
        return None

    @property
    def extra_state_attributes(self) -> dict:
        p = self._person or {}
        return {
            "person_uid": self._uid,
            "full_name": p.get("name"),
            "phone": (p.get("phones") or [None])[0],
            "phones": p.get("phones"),
            "email": p.get("email"),
            "tracked_device_mac": p.get("tracked_device_mac"),
            "ip": next((d["current_ip"] for d in p.get("devices", []) if d["mac"] == p.get("tracked_device_mac")), None),
            "device_count": len([d for d in p.get("devices", []) if not d["revoked"]]),
            "blocked": p.get("blocked"),
            "home_changed_at": p.get("home_changed_at"),
        }
