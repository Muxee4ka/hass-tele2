"""Config flow for the Tele2 (t2) integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback

from tele2api import Tele2Api, Tele2ApiError, Tele2AuthError

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
)

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PHONE): str,
        vol.Optional(CONF_IMPERSONATE, default=DEFAULT_IMPERSONATE): str,
    }
)
SMS_SCHEMA = vol.Schema({vol.Required("code"): str})


class Tele2ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Tele2 config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._phone: str | None = None
        self._api: Tele2Api | None = None
        self._impersonate: str = DEFAULT_IMPERSONATE

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        self._phone = entry_data[CONF_PHONE]
        return await self.async_step_user()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            phone = user_input[CONF_PHONE].strip()
            impersonate = user_input.get(CONF_IMPERSONATE, DEFAULT_IMPERSONATE)
            await self.async_set_unique_id(phone)
            if self.source != "reauth":
                self._abort_if_unique_id_configured()

            try:
                api = await self.hass.async_add_executor_job(
                    lambda: Tele2Api(phone, impersonate=impersonate)
                )
                await self.hass.async_add_executor_job(api.get_sms_code)
            except Tele2ApiError:
                _LOGGER.warning("t2 refused the SMS code request")
                errors["base"] = "sms_failed"
            except Exception:  # noqa: BLE001 - sync client may raise anything
                _LOGGER.exception("Error requesting SMS code from t2")
                errors["base"] = "cannot_connect"
            else:
                self._phone = phone
                self._api = api
                self._impersonate = impersonate
                return await self.async_step_sms()
        return self.async_show_form(
            step_id="user", data_schema=USER_SCHEMA, errors=errors
        )

    async def async_step_sms(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            assert self._api is not None and self._phone is not None
            try:
                access, refresh = await self.hass.async_add_executor_job(
                    self._api.authorization, user_input["code"]
                )
            except Tele2AuthError:
                _LOGGER.warning("t2 rejected the SMS code")
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001 - sync client may raise anything
                _LOGGER.exception("Error authorizing with t2")
                errors["base"] = "cannot_connect"
            else:
                data = {
                    CONF_PHONE: self._phone,
                    CONF_ACCESS_TOKEN: access,
                    CONF_REFRESH_TOKEN: refresh,
                    CONF_IMPERSONATE: self._impersonate,
                }
                if self.source == "reauth":
                    return self.async_update_reload_and_abort(
                        self._get_reauth_entry(), data=data
                    )
                return self.async_create_entry(title=self._phone, data=data)
        return self.async_show_form(
            step_id="sms", data_schema=SMS_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return Tele2OptionsFlow()


class Tele2OptionsFlow(OptionsFlow):
    """Handle Tele2 options (poll interval)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        current_impersonate = self.config_entry.options.get(
            CONF_IMPERSONATE,
            self.config_entry.data.get(CONF_IMPERSONATE, DEFAULT_IMPERSONATE),
        )
        current_boost_interval = self.config_entry.options.get(
            CONF_BOOST_INTERVAL, DEFAULT_BOOST_INTERVAL
        )
        current_boost_cost = self.config_entry.options.get(
            CONF_BOOST_COST, DEFAULT_BOOST_COST
        )
        current_manage_slaves = self.config_entry.options.get(
            CONF_MANAGE_SLAVES, DEFAULT_MANAGE_SLAVES
        )
        current_slave_market = self.config_entry.options.get(
            CONF_SLAVE_MARKET, DEFAULT_SLAVE_MARKET
        )
        current_manage_services = self.config_entry.options.get(
            CONF_MANAGE_SERVICES, DEFAULT_MANAGE_SERVICES
        )
        schema = vol.Schema(
            {
                vol.Optional(CONF_SCAN_INTERVAL, default=current_interval): vol.All(
                    vol.Coerce(int), vol.Range(min=60)
                ),
                vol.Optional(
                    CONF_IMPERSONATE, default=current_impersonate
                ): str,
                vol.Optional(
                    CONF_BOOST_INTERVAL, default=current_boost_interval
                ): vol.All(vol.Coerce(int), vol.Range(min=1)),
                vol.Optional(
                    CONF_BOOST_COST, default=current_boost_cost
                ): vol.All(vol.Coerce(float), vol.Range(min=0)),
                vol.Optional(
                    CONF_MANAGE_SLAVES, default=current_manage_slaves
                ): bool,
                vol.Optional(
                    CONF_SLAVE_MARKET, default=current_slave_market
                ): bool,
                vol.Optional(
                    CONF_MANAGE_SERVICES, default=current_manage_services
                ): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
