"""Tests for the Tele2 config flow."""
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from tele2api import Tele2ApiError, Tele2AuthError

from custom_components.tele2.const import CONF_IMPERSONATE, CONF_PHONE, DOMAIN


async def _start(hass):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_full_flow(hass, patch_api):
    patch_api.get_sms_code.return_value = "OK"
    patch_api.authorization.return_value = ("access-1", "refresh-1")

    result = await _start(hass)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PHONE: "79991234567"}
    )
    assert result["step_id"] == "sms"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": "123456"}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "79991234567"
    assert result["data"][CONF_PHONE] == "79991234567"
    assert result["data"]["access_token"] == "access-1"
    assert result["data"][CONF_IMPERSONATE] == "firefox133"


async def test_custom_impersonate(hass, patch_api):
    patch_api.get_sms_code.return_value = "OK"
    patch_api.authorization.return_value = ("access-1", "refresh-1")

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_PHONE: "79991234567", CONF_IMPERSONATE: "safari18_0"},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": "123456"}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_IMPERSONATE] == "safari18_0"


async def test_sms_request_fails(hass, patch_api):
    patch_api.get_sms_code.side_effect = Tele2ApiError("Не удалось отправить SMS")
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PHONE: "79991234567"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"]["base"] == "sms_failed"


async def test_user_step_handles_client_exception(hass, patch_api):
    """A raising sync client must not crash the flow (e.g. t2 returns non-JSON)."""
    patch_api.get_sms_code.side_effect = ValueError("unexpected character")
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PHONE: "79991234567"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"]["base"] == "cannot_connect"


async def test_sms_step_handles_client_exception(hass, patch_api):
    """A raising authorization call must surface an error, not a 500."""
    patch_api.get_sms_code.return_value = "OK"
    patch_api.authorization.side_effect = ValueError("unexpected character")
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PHONE: "79991234567"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": "123456"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "sms"
    assert result["errors"]["base"] == "cannot_connect"


async def test_auth_fails(hass, patch_api):
    patch_api.get_sms_code.return_value = "OK"
    patch_api.authorization.side_effect = Tele2AuthError("Неверный код")
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PHONE: "79991234567"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": "000000"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "sms"
    assert result["errors"]["base"] == "invalid_auth"


async def test_duplicate_aborts(hass, patch_api):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    MockConfigEntry(domain=DOMAIN, unique_id="79991234567").add_to_hass(hass)
    patch_api.get_sms_code.return_value = "OK"
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PHONE: "79991234567"}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow(hass, patch_api):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="79991234567",
        data={CONF_PHONE: "79991234567", "access_token": "old", "refresh_token": "old"},
    )
    entry.add_to_hass(hass)
    patch_api.get_sms_code.return_value = "OK"
    patch_api.authorization.return_value = ("access-2", "refresh-2")

    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PHONE: "79991234567"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": "123456"}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["access_token"] == "access-2"


async def test_options_flow_sets_slave_toggles(hass, patch_api):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.tele2.const import (
        CONF_MANAGE_SLAVES,
        CONF_SCAN_INTERVAL,
        CONF_SLAVE_MARKET,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="79991234567",
        data={
            CONF_PHONE: "79991234567",
            "access_token": "header.eyJleHAiOjk5OTk5OTk5OTl9.sig",
            "refresh_token": "r",
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SCAN_INTERVAL: 600, CONF_MANAGE_SLAVES: True, CONF_SLAVE_MARKET: True},
    )
    assert result["type"].value == "create_entry"
    assert entry.options[CONF_SLAVE_MARKET] is True
    assert entry.options[CONF_MANAGE_SLAVES] is True


async def test_options_flow_sets_manage_services(hass, patch_api):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.tele2.const import CONF_MANAGE_SERVICES, CONF_SCAN_INTERVAL

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="79991234567",
        data={
            CONF_PHONE: "79991234567",
            "access_token": "header.eyJleHAiOjk5OTk5OTk5OTl9.sig",
            "refresh_token": "r",
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 600, CONF_MANAGE_SERVICES: False}
    )
    assert result["type"].value == "create_entry"
    assert entry.options[CONF_MANAGE_SERVICES] is False
