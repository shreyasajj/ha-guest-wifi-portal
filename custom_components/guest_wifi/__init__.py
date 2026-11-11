"""Guest Wi-Fi portal integration (OPNsense captive portal + Nextcloud contacts)."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PortalClient, PortalConflict, PortalError
from .const import CONF_TOKEN, CONF_URL, CONF_VERIFY_SSL, DOMAIN
from .coordinator import GuestWifiCoordinator

PLATFORMS = [Platform.DEVICE_TRACKER, Platform.BINARY_SENSOR, Platform.SENSOR]

type GuestWifiConfigEntry = ConfigEntry[GuestWifiCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: GuestWifiConfigEntry) -> bool:
    client = PortalClient(async_get_clientsession(hass, verify_ssl=entry.data.get(CONF_VERIFY_SSL, True)),
                          entry.data[CONF_URL], entry.data[CONF_TOKEN], entry.data.get(CONF_VERIFY_SSL, True))
    coordinator = GuestWifiCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    coordinator.start()
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GuestWifiConfigEntry) -> bool:
    await entry.runtime_data.stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _options_updated(hass: HomeAssistant, entry: GuestWifiConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _coordinator(hass: HomeAssistant) -> GuestWifiCoordinator:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED and isinstance(getattr(entry, "runtime_data", None), GuestWifiCoordinator):
            return entry.runtime_data
    raise HomeAssistantError("Guest Wi-Fi is not set up")


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, "approve_request"):
        return

    async def call(fn, *args, **kw):
        coord = _coordinator(hass)
        try:
            result = await fn(coord.client, *args, **kw)
        except PortalConflict as exc:
            raise HomeAssistantError(f"Already resolved: {exc}") from exc
        except PortalError as exc:
            raise HomeAssistantError(str(exc)) from exc
        await coord.async_request_refresh()
        return result

    async def approve(c: ServiceCall):
        return await call(lambda cl: cl.approve(c.data["request_id"], c.data["save_birthday"], c.data.get("contact_uid")))

    async def deny(c: ServiceCall):
        return await call(lambda cl: cl.deny(c.data["request_id"]))

    async def revoke_device(c: ServiceCall):
        ref = c.data.get("device_id") or c.data.get("mac")
        if not ref:
            raise HomeAssistantError("Pass device_id or mac")
        return await call(lambda cl: cl.revoke_device(str(ref)))

    async def revoke_person(c: ServiceCall):
        return await call(lambda cl: cl.revoke_person(c.data["person_uid"]))

    opt = SupportsResponse.OPTIONAL
    hass.services.async_register(DOMAIN, "approve_request", approve, vol.Schema({
        vol.Required("request_id"): cv.string,
        vol.Optional("save_birthday", default=True): cv.boolean,
        vol.Optional("contact_uid"): cv.string,
    }), supports_response=opt)
    hass.services.async_register(DOMAIN, "deny_request", deny, vol.Schema({vol.Required("request_id"): cv.string}),
                                 supports_response=opt)
    hass.services.async_register(DOMAIN, "revoke_device", revoke_device, vol.Schema({
        vol.Optional("device_id"): vol.Any(cv.positive_int, cv.string),
        vol.Optional("mac"): cv.string,
    }), supports_response=opt)
    hass.services.async_register(DOMAIN, "revoke_person", revoke_person,
                                 vol.Schema({vol.Required("person_uid"): cv.string}), supports_response=opt)
