# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Home Assistant **custom integration** for **t2 (Tele2 Russia)** subscribers,
distributed via HACS. It surfaces account/marketplace data as sensors and
switches, and exposes marketplace + SIM operations as HA services. All the t2
HTTP/protocol logic lives in the external [`tele2api`](https://github.com/Muxee4ka/tele2api)
package (a manifest requirement, installed from git) — this repo only contains
the HA-side wrapping. The integration code is in `custom_components/tele2/`.

## Commands

This is a **Windows-hosted** project (PyCharm) edited from WSL; the virtualenv is
a Windows venv. Run Python via the Windows interpreter:

```bash
.venv/Scripts/python.exe -m pytest            # full test suite (~74 tests)
.venv/Scripts/python.exe -m pytest tests/test_coordinator.py::test_... -q   # single test
```

Tests use `pytest-homeassistant-custom-component`; `pytest.ini` sets
`asyncio_mode = auto` so `async def test_*` needs no decorator. `conftest.py`
disables `pytest_socket`'s socket block on Windows (the asyncio self-pipe trips
it) — the t2 API is fully mocked via the `mock_api` fixture, so no real network
is hit. There is no lint/build step.

### Running HA locally

```bash
docker compose up --build
```

Builds HA `:stable` with `tele2api` pre-installed (`Dockerfile`), mounts the
integration and blueprints into a container, persists config in `.ha-config/`
(gitignored), serves on `:8123`, `TZ=Europe/Moscow`. Edits to the integration
take effect after a container restart.

`main.py` is a gitignored local sandbox that hits the real API with a real phone
number — not part of the integration.

## Architecture

Standard modern config-entry integration. The non-obvious, cross-file design
decisions:

- **Async wrapper over a sync library** (`client.py`). `tele2api.Tele2Api` is
  synchronous; `Tele2Client.async_call(method_name, *args)` runs any named API
  method in the executor and **lazily refreshes the token** before each call
  (`async_ensure_token` asks the library `api.is_token_expired(TOKEN_REFRESH_MARGIN)`).
  New token pairs are persisted back into the config entry. The library raises
  typed errors (`Tele2ApiError` → `Tele2AuthError`/`Tele2LotError`/`Tele2ServiceError`);
  `async_call` maps any `Tele2AuthError` (dead refresh token, or a 401 mid-call) to
  `ConfigEntryAuthFailed` → HA reauth. This single choke point is why coordinator,
  services and switches all get correct auth propagation.

- **One coordinator fetches the whole account** (`coordinator.py`). A single t2
  token can read the master number *and* its linked "slave" numbers. Each refresh
  builds `Tele2Data{master, subscribers: {msisdn -> SubscriberData}}`. Per-field
  fetches go through `_safe()`, which **swallows transient transport errors at
  DEBUG** (curl timeouts/resets self-heal: the field keeps its old value, next
  cycle retries) but **re-raises `ConfigEntryAuthFailed`** so auth death still
  surfaces. So one flaky field or one number can never fail the whole cycle.

- **Master vs. slave is the central distinction.** Master = the configured
  number; slaves = auto-discovered linked numbers. In API calls, `subscriber`
  kwarg is `None` for the master and the msisdn for a slave (see `_Target` in
  `services.py`). Marketplace lots are **master-only on tested accounts** — slave
  market fetching is gated behind the `slave_market` option (default off).

- **Entities are CoordinatorEntity, one device per number.** Slaves are nested
  under the master via `via_device`. The "Linked numbers" sensor and MiXX switch
  exist only on the master.

- **Switches are conditional** (`switch.py`). A per-service switch is created
  **only** when t2 marks the service `disconnectionAvailabilityStatus.canDisconnect
  == True` (`_can_disconnect`) — most connected services are tariff-bundled and a
  DELETE returns an error, so they stay read-only in the "Connected services"
  sensor. "Connected" is detected by `status == "CONNECTED"` only, *not*
  `showDisconnectButton` (t2 sets that on ~100 available options too). To
  *connect* a missing service, use the `tele2.connect_service` service with its
  `billing_id`.

- **Services target a device, not a number** (`services.py`). `_resolve_target`
  maps the optional `device_id` → `(client, coordinator, msisdn)` via the device
  registry identifiers, so the same service acts on whichever number's device you
  pick. `device_id` is only required when more than one account is configured.

- **`impersonate` (TLS profile) matters.** `tele2api` uses `curl_cffi` to pass
  t2's anti-bot (NGENIX/WAF). The library default is blocked; this integration
  defaults to `firefox133` (`DEFAULT_IMPERSONATE`). If requests start 403ing, the
  fix is usually a different curl_cffi browser profile via the option, not code.

## Conventions

- Money from t2 comes as `{"amount": N, "currency": ".."}` or a bare number;
  always normalize via `_money()` (`sensor.py`) rather than indexing directly.
- New config options: add `CONF_*`/`DEFAULT_*` to `const.py`, wire through
  `config_flow.py` (options flow), `__init__.py` (read `entry.options.get(...)`),
  and the coordinator constructor. Changing options reloads the entry.
- New services: implement in `services.py`, register schema/selectors in
  `services.yaml`, and document in `README.md` + `strings.json`/`translations/`.
- Strings are bilingual: keep `translations/en.json` and `translations/ru.json`
  in sync.

## Docs & planning

`docs/superpowers/specs/` and `docs/superpowers/plans/` hold the design specs and
implementation plans for each feature (multi-number, services management, bulk
boost / auto-timer, etc.) — read the relevant spec before extending a feature.

`scripts/` are one-off generators, not part of the integration: `make_brand.py` /
`make_logo.py` produce HA brand assets from `brand_src/`; `make_expenses_dashboard.py`
writes a "Расходы t2" Lovelace dashboard into HA's `.storage` (run with HA
stopped).
