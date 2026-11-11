"""Coordinator: SSE push for real-time updates, 5-minute polling as a fallback."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import PortalClient, PortalConflict, PortalError, run_event_stream
from .const import ACTION_PREFIX, ACTIONS, CONF_NOTIFY, DOMAIN, EVENT_MAP, POLL_INTERVAL_SECONDS

_LOGGER = logging.getLogger(__name__)


class GuestWifiCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: PortalClient) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN, config_entry=entry,
            update_interval=timedelta(seconds=POLL_INTERVAL_SECONDS),
            request_refresh_debouncer=Debouncer(hass, _LOGGER, cooldown=1.0, immediate=False),
        )
        self.client = client
        self.entry = entry
        self.connected = False
        self._stream_task: asyncio.Task | None = None
        self._notified: set[str] = set()
        self._unsub_action = None

    # ------------------------------------------------------------ polling
    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data = await self.client.snapshot()
        except PortalError as exc:
            raise UpdateFailed(str(exc)) from exc
        # Catch up on approvals we never notified about (e.g. HA was restarting).
        for req in data.get("approvals", []):
            if req["request_id"] not in self._notified:
                await self._notify_request(req)
        return data

    # --------------------------------------------------------------- push
    def start(self) -> None:
        self._stream_task = self.entry.async_create_background_task(
            self.hass, run_event_stream(self.client, self._on_event, self._on_connected), f"{DOMAIN}_events")
        self._unsub_action = self.hass.bus.async_listen("mobile_app_notification_action", self._on_action)

    async def stop(self) -> None:
        if self._unsub_action:
            self._unsub_action()
        if self._stream_task:
            self._stream_task.cancel()

    async def _on_connected(self, connected: bool) -> None:
        if connected != self.connected:
            self.connected = connected
            _LOGGER.info("Guest Wi-Fi live updates %s", "connected" if connected else "disconnected")
            if connected:
                await self.async_request_refresh()

    async def _on_event(self, event: dict) -> None:
        etype, data = event.get("type"), event.get("data", {})
        if etype in EVENT_MAP:
            self.hass.bus.async_fire(EVENT_MAP[etype], data)
        if etype == "approval_requested":
            await self._notify_request(data)
        elif etype == "approval_resolved":
            await self._clear_notification(data.get("request_id"))
        await self.async_request_refresh()

    # ------------------------------------------------------ notifications
    def _notify_targets(self) -> list[tuple[str, str]]:
        raw = self.entry.options.get(CONF_NOTIFY, "") or ""
        out = []
        for part in (p.strip() for p in raw.split(",")):
            if not part:
                continue
            domain, _, service = part.partition(".") if "." in part else ("notify", "", part)
            out.append((domain, service))
        return out

    async def _notify_request(self, req: dict) -> None:
        rid = req.get("request_id")
        if not rid:
            return
        self._notified.add(rid)
        targets = self._notify_targets()
        if not targets:
            return
        created = dt_util.parse_datetime(req.get("created_at") or "") or dt_util.utcnow()
        when = dt_util.as_local(created).strftime("%H:%M")
        message = f"{req.get('contact_name') or 'Someone'} wants to join the guest Wi-Fi.\nEntered birthday: {req.get('entered_birthday')} · {when}"
        data = {
            "tag": rid,
            "group": "guest_wifi",
            "actions": [
                {"action": f"{ACTION_PREFIX}:APPROVE:{rid}", "title": "Approve"},
                {"action": f"{ACTION_PREFIX}:APPROVE_NO_SAVE:{rid}", "title": "Approve (don't save)"},
                {"action": f"{ACTION_PREFIX}:DENY:{rid}", "title": "Deny", "destructive": True},
            ],
            "push": {"interruption-level": "time-sensitive"},
            "priority": "high",
            "ttl": 0,
        }
        for domain, service in targets:
            try:
                await self.hass.services.async_call(domain, service, {
                    "title": "Guest Wi-Fi approval", "message": message, "data": data}, blocking=False)
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("notify %s.%s failed: %s", domain, service, exc)

    async def _clear_notification(self, rid: str | None) -> None:
        if not rid:
            return
        self._notified.discard(rid)
        for domain, service in self._notify_targets():
            try:
                await self.hass.services.async_call(domain, service, {
                    "message": "clear_notification", "data": {"tag": rid}}, blocking=False)
            except Exception as exc:  # noqa: BLE001
                _LOGGER.debug("clear notification failed: %s", exc)

    @callback
    def _on_action(self, event: Event) -> None:
        action = str(event.data.get("action", ""))
        if not action.startswith(f"{ACTION_PREFIX}:"):
            return
        try:
            _, verb, rid = action.split(":", 2)
        except ValueError:
            return
        if verb not in ACTIONS:
            return
        self.hass.async_create_task(self._resolve(verb, rid))

    async def _resolve(self, verb: str, rid: str) -> None:
        try:
            if verb == "DENY":
                await self.client.deny(rid)
            else:
                res = await self.client.approve(rid, save_birthday=(verb == "APPROVE"))
                if res.get("error") or res.get("note"):
                    for domain, service in self._notify_targets():
                        await self.hass.services.async_call(domain, service, {
                            "title": "Guest Wi-Fi", "message": res.get("error") or res.get("note")}, blocking=False)
        except PortalConflict:
            _LOGGER.info("approval %s was already resolved", rid)
        except PortalError as exc:
            _LOGGER.error("could not resolve approval %s: %s", rid, exc)
        await self._clear_notification(rid)
        await self.async_request_refresh()
