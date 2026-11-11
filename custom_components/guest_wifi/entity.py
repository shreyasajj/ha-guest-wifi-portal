"""Shared entity base + helper that adds entities as people/devices appear."""
from __future__ import annotations

from collections.abc import Callable, Iterable

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
    """Add one entity per key the first time a key shows up in coordinator data."""
    known: set[str] = set()

    def _check() -> None:
        new = [k for k in keys(coordinator.data or {}) if k not in known]
        if new:
            known.update(new)
            add_entities([factory(k) for k in new])

    _check()
    return coordinator.async_add_listener(_check)
