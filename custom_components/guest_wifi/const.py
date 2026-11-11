"""Constants for the Guest Wi-Fi integration."""

DOMAIN = "guest_wifi"

CONF_URL = "url"
CONF_TOKEN = "token"
CONF_VERIFY_SSL = "verify_ssl"
CONF_NOTIFY = "notify_service"

POLL_INTERVAL_SECONDS = 300

ACTION_PREFIX = "GUEST_WIFI"
ACTIONS = ("APPROVE_NO_SAVE", "APPROVE", "DENY")  # longest first when parsing

# Portal event type -> Home Assistant event name
EVENT_MAP = {
    "new_device": "guest_wifi_new_device",
    "unidentified_device": "guest_wifi_unidentified_device",
    "approval_requested": "guest_wifi_approval_requested",
    "approval_resolved": "guest_wifi_approval_resolved",
    "person_home": "guest_wifi_person_home",
    "person_away": "guest_wifi_person_away",
    "device_online": "guest_wifi_device_online",
    "device_offline": "guest_wifi_device_offline",
    "device_revoked": "guest_wifi_device_revoked",
    "person_revoked": "guest_wifi_person_revoked",
    "person_unblocked": "guest_wifi_person_unblocked",
    "device_updated": "guest_wifi_device_updated",
}
