"""Tests against a real Home Assistant core with the portal HTTP API mocked."""
from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events, async_mock_service

from custom_components.guest_wifi.const import DOMAIN

URL = "http://portal.test:8080"
RID = "abc123"

SNAPSHOT = {
    "status": {"guests_home": 1, "guests_home_names": ["Maya Chen"], "people": 2, "devices": 2, "devices_online": 1,
               "unidentified": 1, "pending_approvals": 1},
    "people": [
        {"person_uid": "u1", "name": "Maya Chen", "phones": ["+14155550142"], "email": "maya@example.com",
         "blocked": False, "home": True, "home_changed_at": None, "tracked_device_mac": "aa:bb:cc:00:00:01",
         "tracked_device_id": 1, "devices": [
             {"device_id": 1, "mac": "aa:bb:cc:00:00:01", "type": "phone", "nickname": None, "label": "Phone",
              "person_uid": "u1", "person_name": "Maya Chen", "online": True, "revoked": False,
              "current_ip": "10.0.20.5", "first_seen": None, "last_seen": None}]},
        {"person_uid": "u2", "name": "Jordan Lee", "phones": [], "email": None, "blocked": False, "home": False,
         "home_changed_at": None, "tracked_device_mac": None, "tracked_device_id": None, "devices": []},
    ],
    "devices": [
        {"device_id": 1, "mac": "aa:bb:cc:00:00:01", "type": "phone", "nickname": None, "label": "Phone",
         "person_uid": "u1", "person_name": "Maya Chen", "online": True, "revoked": False, "current_ip": "10.0.20.5",
         "first_seen": None, "last_seen": None},
        {"device_id": 2, "mac": "aa:bb:cc:00:00:02", "type": "computer", "nickname": "Work laptop", "label": "Work laptop",
         "person_uid": "u1", "person_name": "Maya Chen", "online": False, "revoked": False, "current_ip": None,
         "first_seen": None, "last_seen": None},
    ],
    "unidentified": [{"mac": "de:ad:be:ef:00:01", "ip": "10.0.20.77", "sources": ["zone"], "session_id": None,
                      "first_seen": "2026-11-10T10:00:00Z", "last_seen": "2026-11-10T10:00:00Z"}],
    "approvals": [{"request_id": RID, "status": "pending", "contact_name": "Sam Rivera", "contact_uids": ["u9"],
                   "entered_birthday": "1990-02-03", "mac": "aa:bb:cc:00:00:09", "client_ip": "10.0.20.9",
                   "user_agent": "iPhone", "created_at": "2026-11-10T10:00:00Z", "expires_at": "2026-11-10T10:10:00Z",
                   "decided_by": None, "chosen_contact_uid": None, "note": None, "error": None}],
}


async def test_config_flow(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.get(f"{URL}/api/status", status=401)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"url": URL + "/", "token": "bad",
                                                                                "verify_ssl": True})
    assert result["type"] is FlowResultType.FORM and result["errors"] == {"base": "invalid_auth"}

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{URL}/api/status", json=SNAPSHOT["status"])
    aioclient_mock.get(f"{URL}/api/snapshot", json=SNAPSHOT)
    aioclient_mock.get(f"{URL}/api/events", text=": ping\n\n")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"url": URL + "/", "token": "good",
                                                                                "verify_ssl": True})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["url"] == URL


async def _setup(hass, aioclient_mock, notify="notify.mobile_app_phone"):
    aioclient_mock.get(f"{URL}/api/snapshot", json=SNAPSHOT)
    aioclient_mock.get(f"{URL}/api/events", text=": ping\n\n")
    entry = MockConfigEntry(domain=DOMAIN, data={"url": URL, "token": "t", "verify_ssl": True},
                            options={"notify_service": notify}, unique_id=URL)
    entry.add_to_hass(hass)
    notify_calls = async_mock_service(hass, "notify", "mobile_app_phone")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, notify_calls


def _entity(hass, platform, unique_suffix):
    reg = er.async_get(hass)
    for e in reg.entities.values():
        if e.platform == DOMAIN and e.domain == platform and e.unique_id.endswith(unique_suffix):
            return hass.states.get(e.entity_id)
    raise AssertionError(f"no {platform} entity ending {unique_suffix}")


async def test_entities(hass: HomeAssistant, aioclient_mock):
    entry, _ = await _setup(hass, aioclient_mock)
    maya = _entity(hass, "device_tracker", "person_u1")
    assert maya.state == "home"
    assert maya.attributes["email"] == "maya@example.com" and maya.attributes["phone"] == "+14155550142"
    assert _entity(hass, "device_tracker", "person_u2").state == "not_home"
    assert _entity(hass, "binary_sensor", "device_aabbcc000001").state == "on"
    assert _entity(hass, "binary_sensor", "device_aabbcc000002").state == "off"
    assert _entity(hass, "sensor", "guests_home").state == "1"
    assert _entity(hass, "sensor", "unidentified").state == "1"
    pending = _entity(hass, "sensor", "pending_approvals")
    assert pending.state == "1" and pending.attributes["requests"][0]["request_id"] == RID
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_pending_approval_notifies_and_action_resolves(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.post(f"{URL}/api/approvals/{RID}/approve", json={"request_id": RID, "status": "approved_no_save"})
    entry, notify_calls = await _setup(hass, aioclient_mock)

    sent = notify_calls[0].data
    assert "Sam Rivera" in sent["message"] and "1990-02-03" in sent["message"]
    assert sent["data"]["tag"] == RID
    assert [a["action"] for a in sent["data"]["actions"]] == [
        f"GUEST_WIFI:APPROVE:{RID}", f"GUEST_WIFI:APPROVE_NO_SAVE:{RID}", f"GUEST_WIFI:DENY:{RID}"]

    hass.bus.async_fire("mobile_app_notification_action", {"action": f"GUEST_WIFI:APPROVE_NO_SAVE:{RID}"})
    await hass.async_block_till_done()
    approve_calls = [c for c in aioclient_mock.mock_calls if str(c[1]).endswith(f"/approvals/{RID}/approve")]
    assert approve_calls and approve_calls[0][2] == {"save_birthday": False}
    clear = [c for c in notify_calls if c.data["message"] == "clear_notification"]
    assert clear and clear[0].data["data"]["tag"] == RID
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_pushed_events_fire_ha_events_and_clear(hass: HomeAssistant, aioclient_mock):
    entry, notify_calls = await _setup(hass, aioclient_mock)
    fired = async_capture_events(hass, "guest_wifi_approval_resolved")
    new_dev = async_capture_events(hass, "guest_wifi_new_device")
    coord = entry.runtime_data
    await coord._on_event({"id": 5, "type": "new_device", "data": {"mac": "aa:bb:cc:00:00:03"}})
    await coord._on_event({"id": 6, "type": "approval_resolved", "data": {"request_id": RID, "status": "denied"}})
    await hass.async_block_till_done()
    assert new_dev[0].data["mac"] == "aa:bb:cc:00:00:03"
    assert fired[0].data["status"] == "denied"
    assert any(c.data["message"] == "clear_notification" and c.data["data"]["tag"] == RID for c in notify_calls)
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_services(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.post(f"{URL}/api/approvals/{RID}/deny", json={"request_id": RID, "status": "denied"})
    aioclient_mock.post(f"{URL}/api/devices/aa:bb:cc:00:00:02/revoke", json={"device_id": 2})
    aioclient_mock.post(f"{URL}/api/people/u1/revoke", json={"person_uid": "u1", "revoked_devices": [], "blocked": True})
    entry, _ = await _setup(hass, aioclient_mock)
    res = await hass.services.async_call(DOMAIN, "deny_request", {"request_id": RID}, blocking=True, return_response=True)
    assert res["status"] == "denied"
    await hass.services.async_call(DOMAIN, "revoke_device", {"mac": "aa:bb:cc:00:00:02"}, blocking=True)
    await hass.services.async_call(DOMAIN, "revoke_person", {"person_uid": "u1"}, blocking=True)
    paths = [str(c[1]) for c in aioclient_mock.mock_calls]
    assert any(p.endswith("/api/devices/aa:bb:cc:00:00:02/revoke") for p in paths)
    assert any(p.endswith("/api/people/u1/revoke") for p in paths)
    assert await hass.config_entries.async_unload(entry.entry_id)
