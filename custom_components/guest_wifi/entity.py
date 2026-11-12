"""Shared entity base + helper that adds and removes entities as people/devices come and go."""
from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import GuestWifiCoordinator


class GuestWifiEntity(CoordinatorEntity[GuestWifiCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: GuestWifiCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Guest Wi-Fi",
            manufacturer="Guest Wi-Fi Portal",
            configuration_url=coordinator.client._url + "/admin",  # noqa: SLF001
        )


def track_new(coordinator: GuestWifiCoordinator, add_entities: Callable, keys: Callable[[dict], Iterable[str]],
              factory: Callable[[str], object]) -> Callable[[], None]:
    """Add one entity per key when it shows up in coordinator data, and remove it when it's gone.

    A person or device leaves the data when the portal revokes or removes it. Its entity is then
    deleted from the entity registry instead of lingering as "unavailable". If it comes back later
    (the person signs in again) it's added again. Nothing is removed while the portal is unreachable.
    """
    known: dict[str, object] = {}

    def _check() -> None:
        if not coordinator.last_update_success:
            return
        current = set(keys(coordinator.data or {}))
        new = [k for k in current if k not in known]
        if new:
            entities = {k: factory(k) for k in new}
            known.update(entities)
            add_entities(list(entities.values()))
        gone = [k for k in known if k not in current]
        if gone:
            registry = er.async_get(coordinator.hass)
            for k in gone:
                entity = known.pop(k)
                entity_id = getattr(entity, "entity_id", None)
                if entity_id and registry.async_get(entity_id):
                    registry.async_remove(entity_id)

    _check()
    return coordinator.async_add_listener(_check)
