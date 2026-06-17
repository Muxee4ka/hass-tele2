"""Test integration setup/unload."""
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tele2.const import (
    CONF_ACCESS_TOKEN,
    CONF_IMPERSONATE,
    CONF_PHONE,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)


async def test_setup_and_unload(hass: HomeAssistant, patch_api) -> None:
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
    assert entry.entry_id in hass.data[DOMAIN]

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.entry_id not in hass.data[DOMAIN]


async def test_setup_passes_impersonate(hass: HomeAssistant, mock_api) -> None:
    """The stored impersonate profile is forwarded to Tele2Api."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="79991234567",
        data={
            CONF_PHONE: "79991234567",
            CONF_ACCESS_TOKEN: "header.eyJleHAiOjk5OTk5OTk5OTl9.sig",
            CONF_REFRESH_TOKEN: "refresh-token",
            CONF_IMPERSONATE: "safari18_0",
        },
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.tele2.Tele2Api", return_value=mock_api
    ) as ctor:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert ctor.call_args.kwargs["impersonate"] == "safari18_0"


async def test_setup_defaults_impersonate(hass: HomeAssistant, mock_api) -> None:
    """When no impersonate is stored, the working default is used."""
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
    with patch(
        "custom_components.tele2.Tele2Api", return_value=mock_api
    ) as ctor:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert ctor.call_args.kwargs["impersonate"] == "firefox133"
