"""Tests for Tele2Client."""
from unittest.mock import MagicMock

import pytest
from homeassistant.config_entries import ConfigEntryAuthFailed
from tele2api import Tele2AuthError

from custom_components.tele2.client import Tele2Client


@pytest.fixture
def api():
    api = MagicMock()
    api.access_token = "header.payload.sig"
    api.refresh_token = "refresh-token"
    api.is_token_expired.return_value = False  # fresh unless a test says otherwise
    api.get_balance.return_value = 251.4
    api.update_token.return_value = ("new-access", "new-refresh")
    return api


async def test_async_call_runs_method(hass, api):
    client = Tele2Client(hass, api)
    result = await client.async_call("get_balance")
    assert result == 251.4
    api.get_balance.assert_called_once()


async def test_ensure_token_refreshes_when_expiring(hass, api):
    api.is_token_expired.return_value = True
    client = Tele2Client(hass, api)
    await client.async_ensure_token()
    api.update_token.assert_called_once()


async def test_ensure_token_skips_when_fresh(hass, api):
    client = Tele2Client(hass, api)
    await client.async_ensure_token()
    api.update_token.assert_not_called()


async def test_refresh_failure_raises_auth_failed(hass, api):
    api.is_token_expired.return_value = True
    api.update_token.side_effect = Tele2AuthError("invalid_grant")
    client = Tele2Client(hass, api)
    with pytest.raises(ConfigEntryAuthFailed):
        await client.async_ensure_token()


async def test_call_maps_auth_error_to_auth_failed(hass, api):
    """A Tele2AuthError raised mid-call (e.g. a 401) becomes ConfigEntryAuthFailed."""
    api.get_balance.side_effect = Tele2AuthError("token rejected")
    client = Tele2Client(hass, api)
    with pytest.raises(ConfigEntryAuthFailed):
        await client.async_call("get_balance")


async def test_refresh_persists_tokens_to_entry(hass, api):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.tele2.const import (
        CONF_ACCESS_TOKEN,
        CONF_REFRESH_TOKEN,
        DOMAIN,
    )

    api.is_token_expired.return_value = True
    api.update_token.return_value = ("persisted-access", "persisted-refresh")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"phone": "79991234567", CONF_ACCESS_TOKEN: "old", CONF_REFRESH_TOKEN: "old"},
    )
    entry.add_to_hass(hass)
    client = Tele2Client(hass, api, entry)
    await client.async_ensure_token()
    assert entry.data[CONF_ACCESS_TOKEN] == "persisted-access"
    assert entry.data[CONF_REFRESH_TOKEN] == "persisted-refresh"
