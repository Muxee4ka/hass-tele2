"""Tests for diagnostics."""
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tele2.const import (
    CONF_ACCESS_TOKEN,
    CONF_PHONE,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)
from custom_components.tele2.diagnostics import (
    async_get_config_entry_diagnostics,
)


async def test_diagnostics_redacts(hass: HomeAssistant, patch_api):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="79991234567",
        data={
            CONF_PHONE: "79991234567",
            CONF_ACCESS_TOKEN: "header.eyJleHAiOjk5OTk5OTk5OTl9.sig",
            CONF_REFRESH_TOKEN: "refresh-token",
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["entry_data"][CONF_ACCESS_TOKEN] == "**REDACTED**"
    assert diag["entry_data"][CONF_PHONE] == "**REDACTED**"
    subs = diag["data"]["subscribers"]
    master = subs["subscriber_0"]
    assert master["balance"] == 251.4
    assert master["msisdn"] == "**REDACTED**"
    assert master["profile"] == "**REDACTED**"
