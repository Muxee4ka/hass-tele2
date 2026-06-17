"""The Tele2 (t2) integration."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from tele2api import Tele2Api

from .client import Tele2Client
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_BOOST_COST,
    CONF_BOOST_INTERVAL,
    CONF_IMPERSONATE,
    CONF_MANAGE_SERVICES,
    CONF_MANAGE_SLAVES,
    CONF_PHONE,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_SLAVE_MARKET,
    DEFAULT_BOOST_COST,
    DEFAULT_BOOST_INTERVAL,
    DEFAULT_IMPERSONATE,
    DEFAULT_MANAGE_SERVICES,
    DEFAULT_MANAGE_SLAVES,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SLAVE_MARKET,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import Tele2Coordinator
from .services import async_setup_services


@dataclass
class Tele2RuntimeData:
    """Per-entry runtime objects stored in hass.data."""

    client: Tele2Client
    coordinator: Tele2Coordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tele2 from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    phone = entry.data[CONF_PHONE]
    impersonate = entry.options.get(CONF_IMPERSONATE) or entry.data.get(
        CONF_IMPERSONATE, DEFAULT_IMPERSONATE
    )
    api = await hass.async_add_executor_job(
        lambda: Tele2Api(
            phone,
            access_token=entry.data[CONF_ACCESS_TOKEN],
            refresh_token=entry.data[CONF_REFRESH_TOKEN],
            impersonate=impersonate,
        )
    )
    client = Tele2Client(hass, api, entry)

    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    boost_interval = entry.options.get(CONF_BOOST_INTERVAL, DEFAULT_BOOST_INTERVAL)
    boost_cost = entry.options.get(CONF_BOOST_COST, DEFAULT_BOOST_COST)
    manage_slaves = entry.options.get(CONF_MANAGE_SLAVES, DEFAULT_MANAGE_SLAVES)
    slave_market = entry.options.get(CONF_SLAVE_MARKET, DEFAULT_SLAVE_MARKET)
    manage_services = entry.options.get(CONF_MANAGE_SERVICES, DEFAULT_MANAGE_SERVICES)
    coordinator = Tele2Coordinator(
        hass, client, scan_interval, phone, boost_interval, boost_cost,
        manage_slaves=manage_slaves, slave_market=slave_market,
        manage_services=manage_services,
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = Tele2RuntimeData(client, coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_setup_services(hass)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
