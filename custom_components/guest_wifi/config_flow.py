"""Config flow (portal URL + API token) and options flow (notify target for approvals)."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PortalAuthError, PortalClient, PortalError
from .const import CONF_NOTIFY, CONF_TOKEN, CONF_URL, CONF_VERIFY_SSL, DOMAIN


class GuestWifiConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_URL].rstrip("/")
            await self.async_set_unique_id(url)
            self._abort_if_unique_id_configured()
            client = PortalClient(async_get_clientsession(self.hass, verify_ssl=user_input[CONF_VERIFY_SSL]),
                                  url, user_input[CONF_TOKEN], user_input[CONF_VERIFY_SSL])
            try:
                await client.status()
            except PortalAuthError:
                errors["base"] = "invalid_auth"
            except PortalError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title="Guest Wi-Fi", data={**user_input, CONF_URL: url})
        schema = vol.Schema({
            vol.Required(CONF_URL, default=(user_input or {}).get(CONF_URL, "http://")): str,
            vol.Required(CONF_TOKEN): str,
            vol.Required(CONF_VERIFY_SSL, default=True): bool,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return GuestWifiOptionsFlow()


class GuestWifiOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        notify_services = sorted(f"notify.{s}" for s in self.hass.services.async_services().get("notify", {}))
        current = self.config_entry.options.get(CONF_NOTIFY, "")
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({vol.Optional(CONF_NOTIFY, default=current): str}),
            description_placeholders={"services": ", ".join(s for s in notify_services if "mobile_app" in s) or "none found"},
        )
