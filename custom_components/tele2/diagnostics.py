"""Diagnostics for the Tele2 integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_PHONE,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)

TO_REDACT = {CONF_PHONE, CONF_ACCESS_TOKEN, CONF_REFRESH_TOKEN}
TO_REDACT_SUB = {"msisdn", "profile"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    data = runtime.coordinator.data
    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "data": {
            # Keyed positionally (not by msisdn) to avoid leaking phone numbers;
            # each subscriber's own is_master flag identifies the master.
            "subscribers": {
                f"subscriber_{i}": async_redact_data(dict(vars(sub)), TO_REDACT_SUB)
                for i, sub in enumerate(data.subscribers.values())
            },
        },
    }
