"""Small async client for the Guest Wi-Fi portal REST API and its SSE stream."""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)


class PortalError(Exception):
    """Portal unreachable or returned an error."""


class PortalAuthError(PortalError):
    """Token rejected."""


class PortalConflict(PortalError):
    """Request was already resolved."""


class PortalClient:
    def __init__(self, session: aiohttp.ClientSession, url: str, token: str, verify_ssl: bool = True) -> None:
        self._session = session
        self._url = url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        self._ssl = None if verify_ssl else False

    async def _request(self, method: str, path: str, json_body: dict | None = None) -> Any:
        try:
            async with self._session.request(
                method, f"{self._url}{path}", headers=self._headers, json=json_body, ssl=self._ssl,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status == 401:
                    raise PortalAuthError("invalid token")
                if resp.status == 409:
                    raise PortalConflict(await resp.text())
                if resp.status >= 400:
                    raise PortalError(f"{method} {path}: HTTP {resp.status} {await resp.text()}")
                return await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise PortalError(str(exc)) from exc

    async def status(self) -> dict:
        return await self._request("GET", "/api/status")

    async def snapshot(self) -> dict:
        return await self._request("GET", "/api/snapshot")

    async def approve(self, request_id: str, save_birthday: bool = True, contact_uid: str | None = None) -> dict:
        body: dict[str, Any] = {"save_birthday": save_birthday}
        if contact_uid:
            body["contact_uid"] = contact_uid
        return await self._request("POST", f"/api/approvals/{request_id}/approve", body)

    async def deny(self, request_id: str) -> dict:
        return await self._request("POST", f"/api/approvals/{request_id}/deny")

    async def revoke_device(self, ref: str) -> dict:
        return await self._request("POST", f"/api/devices/{ref}/revoke")

    async def revoke_person(self, person_uid: str) -> dict:
        return await self._request("POST", f"/api/people/{person_uid}/revoke")

    async def events(self, last_event_id: str | None) -> AsyncIterator[dict]:
        """Yield events from /api/events until the connection drops."""
        headers = dict(self._headers, Accept="text/event-stream")
        if last_event_id:
            headers["Last-Event-ID"] = last_event_id
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=60)  # server pings every 15 s
        async with self._session.get(f"{self._url}/api/events", headers=headers, ssl=self._ssl, timeout=timeout) as resp:
            if resp.status == 401:
                raise PortalAuthError("invalid token")
            if resp.status >= 400:
                raise PortalError(f"events: HTTP {resp.status}")
            data_lines: list[str] = []
            async for raw in resp.content:
                line = raw.decode("utf-8").rstrip("\r\n")
                if line == "":
                    if data_lines:
                        try:
                            yield json.loads("\n".join(data_lines))
                        except ValueError:
                            _LOGGER.debug("ignoring malformed event")
                    data_lines = []
                elif line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
                # id:/event:/retry:/comments are carried inside the JSON payload or ignored


async def run_event_stream(client: PortalClient, on_event: Callable[[dict], Awaitable[None]],
                           on_connected: Callable[[bool], Awaitable[None]]) -> None:
    """Keep an SSE connection open forever, reconnecting with backoff and replaying missed events."""
    last_id: str | None = None
    delay = 2
    while True:
        try:
            first = True
            async for event in client.events(last_id):
                if first:
                    await on_connected(True)
                    first = False
                    delay = 2
                last_id = str(event.get("id", last_id))
                await on_event(event)
        except asyncio.CancelledError:
            raise
        except PortalAuthError:
            _LOGGER.error("Guest Wi-Fi portal rejected the API token; live updates stopped")
            await on_connected(False)
            return
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("event stream dropped: %s", exc)
        await on_connected(False)
        await asyncio.sleep(delay)
        delay = min(delay * 2, 60)
