# Tele2 (t2) — Home Assistant integration

A config-entry-based Home Assistant custom integration for **t2 (Tele2 Russia)**
subscribers. It shows your account and [t2 Маркет](https://t2.ru) marketplace
data as sensors and exposes marketplace / SIM operations as services. It is
backed by the [`tele2api`](https://github.com/Muxee4ka/tele2api) client and
keeps the access token fresh in the background.

## Features

- **Sensors** for balance, remaining package (data / voice / SMS), rollover
  balances, SIM status, tariff, abonent fee, package-renewal date, linked
  numbers, monthly charges and active marketplace lots (each lot includes its
  listing position and boost-profitability analytics).
- **Marketplace services** to create lots (single or in bulk), reprice, boost
  («ракета») a single lot or **all** lots, delete a lot or **all** lots, and
  **undercut** competitors (demping) for one lot or all lots.
- **Multi-number**: adding your master number auto-discovers every linked
  (slave) number on the account and exposes each as its own device with the full
  sensor set; SIM block/unblock and per-lot services target whichever number's
  device you pick.
- **SIM / data services** to block/unblock the SIM and force a refresh.
- **Service switches** to connect/disconnect t2 add-on services, toggle the MiXX
  subscription, and block/unblock each number's SIM from the dashboard.
- **Automation blueprints** to keep a single lot, or all lots, pinned near the
  top, and to auto-undercut competitors on a schedule.
- Configurable TLS profile (`impersonate`) to get past t2's anti-bot, background
  token refresh, reauth flow, redacted diagnostics, and EN + RU translations.

## Installation

### HACS (custom repository)

1. In HACS → **Integrations** → ⋮ → **Custom repositories**.
2. Add `https://github.com/Muxee4ka/tele2api` as an **Integration**.
3. Install **Tele2 (t2)** and restart Home Assistant.

### Manual

Copy `custom_components/tele2` into your Home Assistant `config/custom_components/`
directory and restart Home Assistant.

## Setup

1. **Settings → Devices & Services → Add Integration → Tele2 (t2)**.
2. Enter your phone number in `79991234567` format. You will receive an SMS code.
3. Enter the SMS code. The integration stores the resulting tokens and creates a
   device with all sensors.

If the refresh token ever dies, Home Assistant raises a reauthentication prompt;
re-enter a fresh SMS code to restore access.

### Options

Under the integration's **Configure** button you can set:

- **Update interval** (default 600 s, min 60 s) — how often data is polled.
- **TLS profile** (`impersonate`, default `firefox133`) — the curl_cffi browser
  profile used to pass t2's anti-bot. If requests start getting blocked, try
  another profile (e.g. `safari18_0`, `chrome131`).
- **Boost interval / Boost cost** — used only to compute the per-lot
  profitability analytics (how long boosting a lot stays profitable).
- **Manage linked numbers** (default on) — auto-discover the account's linked
  numbers and create a device per number. Turn off to keep only the master.
- **Enable marketplace on linked numbers** (default off) — also fetch
  marketplace lots for linked numbers. Leave off unless your account allows it:
  on the accounts tested, the marketplace is **master-only** (the t2 API returns
  no lot data for linked numbers), so account sensors and SIM block/unblock work
  for every number but marketplace operations are only reliable on the master.
- **Manage services** (default on) — fetch the account's connected services and
  expose a switch per service. Turn off to drop the service switches and the
  Connected services sensor (MiXX and SIM-block switches stay).

## Services & switches

The integration adds a `switch` platform:

- **Service switches** — one switch per connected service the API marks as
  **removable** (`disconnectionAvailabilityStatus.canDisconnect == True`). Most
  connected services are tariff-bundled and cannot be disconnected, so they get
  **no switch** (they're still listed, read-only, in the Connected services
  sensor). Turning a switch **off** disconnects the service. To **connect** a
  service you don't have yet, call `tele2.connect_service` with its `billing_id`
  — find the id in the **Connected services** sensor's attributes.
- **MiXX subscription** — a switch on the master (uses `mixx_update_subscribe`).
- **SIM block** — a switch on **every** number (master and linked); on = SIM
  suspended. This mirrors the `tele2.set_status` service for dashboard use.

> Connecting/disconnecting some paid services may be gated by t2 (and a few are
> account-specific); if a toggle fails, the error surfaces in Home Assistant and
> the service stays as it was.

## Linked numbers (multi-number)

If your master number has other numbers linked to it (t2 «Управление номерами»),
adding the master is enough: the integration discovers them via the account's
single token and creates one **device per number**, with the linked numbers
nested under the master (`via_device`). Each number gets its own balance /
package / tariff / SIM-status sensors; the **Linked numbers** sensor lives only
on the master.

To act on a specific number, target that number's **device** when calling a
service (e.g. `tele2.set_status` on a linked number's device blocks just that
SIM). New numbers linked later are picked up after reloading the integration.

## Sensors

| Sensor          | Description                                            |
| --------------- | ------------------------------------------------------ |
| Balance         | Account balance (RUB)                                  |
| Data remaining  | Remaining data package (GB)                            |
| Voice remaining | Remaining minutes                                      |
| SMS remaining   | Remaining SMS                                          |
| Rollover data / voice / SMS | Carried-over package balances                  |
| SIM status      | SIM state (e.g. `ACTIVATED`)                           |
| Tariff          | Current tariff name                                    |
| Abonent fee     | Actual monthly fee paid, reflecting discounts (`base_fee` attribute has the list price) |
| Package renews  | Timestamp when the tariff package renews               |
| Linked numbers  | Count of linked numbers (`numbers` attribute)          |
| Connected services | Count of connected services; `services` attribute lists `{billing_id, name, fee, status}` and `monthly_fee` sums their abonent fees |
| Monthly charges | Sum of monthly charges (RUB), with a `charges` attribute |
| Active lots     | Number of active lots, with a `lots` attribute. Each lot includes its `position`, `cost_per_hour` and `profitable_hours` (boost-profitability analytics) |

## Services

All services accept an optional `device_id` to target a specific number — the
master or any linked number's device (only required when more than one account
is configured, but use it to pick which linked number an action applies to).

| Service              | Description                                         |
| -------------------- | --------------------------------------------------- |
| `tele2.create_lot`   | Create a marketplace lot (`traffic_type`, `value`, `amount`, optional `emojis`). Returns the new `lot_id`. |
| `tele2.create_lots`  | Create several lots at once from a list of `volumes` at one `amount`. Returns `{created, failed, errors}`. |
| `tele2.patch_lot`    | Change a lot's price (`lot_id`, `amount`).          |
| `tele2.premium_lot`  | Boost a lot to the top of the listing (costs 5 RUB). |
| `tele2.premium_all_lots` | Boost **all** active lots at once (optionally filtered by `traffic_type`). Returns `{boosted, failed, errors}`. |
| `tele2.undercut_lot` | Lower a lot's price just below the cheapest competitor (`lot_id`, optional `step`, `min_amount`). |
| `tele2.undercut_all_lots` | Undercut **all** active lots below their cheapest competitors. Returns `{changed, results}`. |
| `tele2.delete_lot`   | Remove a lot from sale (`lot_id`).                  |
| `tele2.delete_all_lots` | Remove **all** active lots (optionally filtered by `traffic_type`). |
| `tele2.set_status`   | Block/unblock the SIM (`status`: `ACTIVATED`/`SUSPENDED`). |
| `tele2.connect_service` | Connect an add-on service by its `billing_id` (see the Connected services sensor). Disconnecting is done via the service's switch. |
| `tele2.refresh`      | Force an immediate data refresh.                    |

> **Note:** buying lots from the marketplace is **not** supported in this
> version — each purchase requires a per-transaction SMS confirmation that does
> not map cleanly onto a service call.

## Blueprints

Import via **Settings → Automations & Scenes → Blueprints → Import Blueprint**.

- `blueprints/automation/tele2/auto_hold_lot.yaml` — keep a **single** lot on
  top: checks its `position` via the **Active lots** sensor and calls
  `tele2.premium_lot` whenever it falls below your threshold.
- `blueprints/automation/tele2/auto_hold_all_lots.yaml` — keep **all** lots on
  top: calls `tele2.premium_all_lots` every N minutes during the active hours
  you choose.
- `blueprints/automation/tele2/auto_undercut.yaml` — **auto-demping**: calls
  `tele2.undercut_all_lots` on a schedule to keep your lots priced just below
  competitors (respecting a minimum price).

> Active hours in the blueprints use Home Assistant's own timezone — set
> `TZ=Europe/Moscow` (the bundled `docker-compose.yml` already does) for Moscow
> time.

## Credits

Powered by [`tele2api`](https://github.com/Muxee4ka/tele2api).
