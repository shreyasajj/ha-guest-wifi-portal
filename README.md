# Guest Wi‑Fi Portal for Home Assistant

Live presence, device and approval data from the self-hosted [guest Wi‑Fi portal](https://github.com/shreyasajj/guest-wifi-portal) (OPNsense captive portal + Nextcloud contacts). It also sends actionable phone notifications so you can let guests in from anywhere.

- **Push-based:** keeps a Server-Sent Events connection to the portal and replays missed events after a reconnect. A full snapshot every 5 minutes is the fallback.
- **Approvals on your phone:** Approve / Approve without saving / Deny buttons. The notification disappears from every phone as soon as the request is handled anywhere (admin UI, another phone, or expiry).

## Install

### HACS (recommended)

1. HACS > ⋮ > **Custom repositories** > add `https://github.com/shreyasajj/ha-guest-wifi-portal`, category **Integration**.
2. Install **Guest Wi‑Fi Portal**, then restart Home Assistant.

### Manual

Copy `custom_components/guest_wifi` to `/config/custom_components/guest_wifi` and restart.

## Set up

1. In the [portal](https://github.com/shreyasajj/guest-wifi-portal)'s `.env`, add a token to `API_TOKENS`. Make sure Home Assistant's IP is inside `ADMIN_ALLOWED_NETWORKS`.
2. **Settings > Devices & services > Add integration > Guest Wi‑Fi Portal**.
   - **Portal URL**: the LAN address, e.g. `http://192.168.1.20:8080` or `https://wifi-admin.home.example`. Don't use the guest hostname: `/api` is blocked there.
   - **API token**: the token from step 1.
3. Open the integration's **Configure** dialog and set the **notify service** for approvals, e.g. `notify.mobile_app_pixel_8`. Separate several with commas.

### Notification setup

1. Install the Home Assistant **Companion app** on your phone and sign in. This creates `notify.mobile_app_<phone>`.
2. Enter that service in the options (step 3 above).
3. Test: sign in on the guest network with a contact that has no birthday. You should get:

   > **Guest Wi‑Fi approval**
   > Sam Rivera wants to join the guest Wi‑Fi.
   > Entered birthday: 1990‑02‑03 · 14:32
   > [Approve] [Approve (don't save)] [Deny]

   - **Approve** writes the birthday to the contact in Nextcloud. If several contacts matched, it updates the first one, and the portal's audit log flags it so you can check.
   - Action IDs are `GUEST_WIFI:APPROVE:<request_id>`, `GUEST_WIFI:APPROVE_NO_SAVE:<request_id>` and `GUEST_WIFI:DENY:<request_id>`.
   - The notification `tag` is the request ID. When the request is resolved anywhere, the integration sends `clear_notification` with that tag.
   - On iOS it's sent as *time-sensitive*, on Android as high priority.

## Entities

| Entity | Example | State |
|---|---|---|
| `device_tracker` per person | `device_tracker.guest_wi_fi_maya_chen` | `home` / `not_home` from their tracked phone. Attributes: `full_name`, `phone`, `phones`, `email`, `tracked_device_mac`, `ip`, `device_count`, `blocked` |
| `binary_sensor` per device (connectivity) | `binary_sensor.guest_wi_fi_maya_chen_work_laptop` | `on` when online. Attributes: `mac`, `type`, `nickname`, `person_name`, `current_ip`, `first_seen`, `last_seen`, `device_id` |
| `sensor.guest_wi_fi_guests_home` | | number of people home (`names` attribute) |
| `sensor.guest_wi_fi_unidentified_devices` | | MACs allowed or in session in OPNsense but unknown to the portal |
| `sensor.guest_wi_fi_pending_approvals` | | open requests (`requests` attribute with IDs) |

New people and devices get entities automatically. Revoked devices become unavailable.

Tip: add a person's tracker to a Home Assistant **Person** together with the UniFi Network tracker for their phone, for faster "left home" detection.

## Events

`guest_wifi_new_device`, `guest_wifi_unidentified_device`, `guest_wifi_approval_requested`, `guest_wifi_approval_resolved`, `guest_wifi_person_home`, `guest_wifi_person_away`, `guest_wifi_device_online`, `guest_wifi_device_offline`, `guest_wifi_device_revoked`, `guest_wifi_person_revoked`, `guest_wifi_person_unblocked`, `guest_wifi_device_updated`

## Services

| Service | Fields |
|---|---|
| `guest_wifi.approve_request` | `request_id`, `save_birthday` (default `true`), `contact_uid` (optional) |
| `guest_wifi.deny_request` | `request_id` |
| `guest_wifi.revoke_device` | `device_id` or `mac` |
| `guest_wifi.revoke_person` | `person_uid` (revokes all devices and blocks future sign-ins) |

All of them return the portal's response when called with `return_response`.

## Example automations

```yaml
- alias: Announce guests arriving
  triggers:
    - trigger: event
      event_type: guest_wifi_person_home
  actions:
    - action: tts.speak
      target: { entity_id: tts.home_assistant_cloud }
      data:
        media_player_entity_id: media_player.kitchen
        message: "{{ trigger.event.data.name.split(' ')[0] }} just arrived."

- alias: Auto-approve family during the party
  triggers:
    - trigger: event
      event_type: guest_wifi_approval_requested
  conditions:
    - condition: state
      entity_id: input_boolean.party_mode
      state: "on"
  actions:
    - action: guest_wifi.approve_request
      data:
        request_id: "{{ trigger.event.data.request_id }}"
        save_birthday: false

- alias: Warn about unidentified devices
  triggers:
    - trigger: event
      event_type: guest_wifi_unidentified_device
  actions:
    - action: notify.mobile_app_pixel_8
      data:
        title: Unknown device on guest Wi‑Fi
        message: "{{ trigger.event.data.mac }} ({{ trigger.event.data.ip or 'no IP' }})"
```

## Development

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -r requirements-test.txt   # pinned to HA 2026.2.3
pytest -q
```

To test against a newer Home Assistant, bump `pytest-homeassistant-custom-component` in `requirements-test.txt`. Each release pins one HA version, and releases for HA 2026.3 and later need Python 3.14, so change `python-version` in the workflow too.

### Repository setup

CI (`.github/workflows/ci.yml`) runs on every pull request and push to `main`:

- **Tests:** the integration tests against a real Home Assistant core.
- **Hassfest:** Home Assistant's own validator for `manifest.json`, `services.yaml`, `strings.json` and translations.
- **HACS validation:** checks the repo is installable through HACS.
- **CI passed:** fails if any of the above failed. It's the only check `main` requires.

Create the repo and block merges unless CI passes (from this folder):

```bash
git init -b main && git add . && git commit -m "Initial commit"
gh repo create ha-guest-wifi-portal --public --source . --push \
  --description "Home Assistant integration for the self-hosted guest Wi-Fi portal"
gh repo edit shreyasajj/ha-guest-wifi-portal --add-topic home-assistant,hacs,hacs-integration
.github/protect-main.sh shreyasajj/ha-guest-wifi-portal
```

The repo must be **public**: HACS can't install from private repos, and the HACS validation checks for a description and topics. The ruleset (`.github/ruleset-main.json`) requires a pull request with **CI passed** green and up to date, and blocks force-pushes and deleting `main`. You can merge your own PRs.

**Releases:** HACS installs the latest commit on `main` when there are no releases. To give users versions, bump `version` in `manifest.json` and publish a GitHub release with a matching tag, e.g. `gh release create v0.1.0 --generate-notes`.
