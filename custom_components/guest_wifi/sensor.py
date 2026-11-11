"""Count sensors: guests home, unidentified devices, pending approvals."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import GuestWifiConfigEntry
from .entity import GuestWifiEntity


@dataclass(frozen=True, kw_only=True)
class CountDescription(SensorEntityDescription):
    value: Callable[[dict], int]
    attrs: Callable[[dict], dict]


SENSORS = (
    CountDescription(
        key="guests_home", name="Guests home", icon="mdi:account-group", state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="guests",
        value=lambda d: d["status"]["guests_home"],
        attrs=lambda d: {"names": d["status"]["guests_home_names"]},
    ),
    CountDescription(
        key="unidentified", name="Unidentified devices", icon="mdi:help-network", state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="devices",
        value=lambda d: len(d.get("unidentified", [])),
        attrs=lambda d: {"devices": [{"mac": u["mac"], "ip": u["ip"], "sources": u["sources"]} for u in d.get("unidentified", [])]},
    ),
    CountDescription(
        key="pending_approvals", name="Pending approvals", icon="mdi:account-clock", state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="requests",
        value=lambda d: len(d.get("approvals", [])),
        attrs=lambda d: {"requests": [{"request_id": a["request_id"], "contact_name": a["contact_name"],
                                       "entered_birthday": a["entered_birthday"], "created_at": a["created_at"],
                                       "contact_uids": a["contact_uids"]} for a in d.get("approvals", [])]},
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: GuestWifiConfigEntry, add: AddEntitiesCallback) -> None:
    add(CountSensor(entry.runtime_data, desc) for desc in SENSORS)


class CountSensor(GuestWifiEntity, SensorEntity):
    entity_description: CountDescription

    def __init__(self, coordinator, description: CountDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"

    @property
    def native_value(self) -> int | None:
        return self.entity_description.value(self.coordinator.data) if self.coordinator.data else None

    @property
    def extra_state_attributes(self) -> dict:
        d = self.coordinator.data
        return {**self.entity_description.attrs(d), "live_updates": self.coordinator.connected} if d else {}
