"""Tests for Tele2 switches."""
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from tele2api import Tele2ServiceError

from custom_components.tele2.const import (
    CONF_ACCESS_TOKEN,
    CONF_PHONE,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)

PHONE = "79991234567"


def _svc(billing_id, name, connected=True, fee=100.0, slug="", can_disconnect=True):
    return {
        "billingId": billing_id, "name": name, "slug": slug,
        "abonentFee": {"amount": fee, "period": "month"},
        "category": "internet",
        "showDisconnectButton": connected,
        "showConnectButton": not connected,
        "status": "CONNECTED" if connected else "AVAILABLE",
        "disconnectionAvailabilityStatus": {"canDisconnect": can_disconnect},
    }


async def _setup(hass, patch_api):
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=PHONE,
        data={
            CONF_PHONE: PHONE,
            CONF_ACCESS_TOKEN: "header.eyJleHAiOjk5OTk5OTk5OTl9.sig",
            CONF_REFRESH_TOKEN: "refresh-token",
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _eid(hass, unique_id):
    return er.async_get(hass).async_get_entity_id("switch", DOMAIN, unique_id)


async def test_service_switch_disconnect(hass: HomeAssistant, patch_api):
    patch_api.get_services.return_value = [_svc("46556", "Unlim weekends")]
    await _setup(hass, patch_api)
    eid = _eid(hass, f"{PHONE}_service_46556")
    assert eid is not None
    assert hass.states.get(eid).state == "on"
    await hass.services.async_call("switch", "turn_off", {"entity_id": eid}, blocking=True)
    patch_api.disconnect_service.assert_called_once_with("46556")


async def test_service_switch_connect(hass: HomeAssistant, patch_api):
    patch_api.get_services.return_value = [_svc("46556", "Unlim weekends")]
    await _setup(hass, patch_api)
    eid = _eid(hass, f"{PHONE}_service_46556")
    await hass.services.async_call("switch", "turn_on", {"entity_id": eid}, blocking=True)
    patch_api.connect_service.assert_called_once_with("46556")


async def test_service_switch_attributes_paid(hass: HomeAssistant, patch_api):
    patch_api.get_services.return_value = [_svc("46556", "Paid opt", fee=60.0)]
    await _setup(hass, patch_api)
    attrs = hass.states.get(_eid(hass, f"{PHONE}_service_46556")).attributes
    assert attrs["abonent_fee"] == 60.0
    assert attrs["paid"] is True


async def test_failed_disconnect_keeps_switch_on(hass: HomeAssistant, patch_api):
    # A failed disconnect must leave the switch reflecting reality (on), not the
    # optimistic off, without needing a reload.
    patch_api.get_services.return_value = [_svc("46556", "Removable")]
    patch_api.disconnect_service.side_effect = Tele2ServiceError("UNKNOWN_ERROR")
    await _setup(hass, patch_api)
    eid = _eid(hass, f"{PHONE}_service_46556")
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("switch", "turn_off", {"entity_id": eid}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(eid).state == "on"


async def test_no_switch_for_non_disconnectable_service(hass: HomeAssistant, patch_api):
    # A connected but tariff-bundled service (canDisconnect=False) must NOT get a
    # switch — disconnecting it would always fail with UNKNOWN_ERROR.
    patch_api.get_services.return_value = [
        _svc("46556", "Removable", can_disconnect=True),
        _svc("99999", "Bundled", can_disconnect=False),
    ]
    await _setup(hass, patch_api)
    assert _eid(hass, f"{PHONE}_service_46556") is not None
    assert _eid(hass, f"{PHONE}_service_99999") is None


async def test_mixx_switch(hass: HomeAssistant, patch_api):
    patch_api.get_services.return_value = [_svc("9", "Подписка MiXX", slug="mixx")]
    await _setup(hass, patch_api)
    eid = _eid(hass, f"{PHONE}_mixx")
    assert eid is not None
    assert hass.states.get(eid).state == "on"
    await hass.services.async_call("switch", "turn_off", {"entity_id": eid}, blocking=True)
    patch_api.mixx_update_subscribe.assert_called_once_with("disable")


async def test_sim_block_switch_master(hass: HomeAssistant, patch_api):
    patch_api.get_status.return_value = "ACTIVATED"
    await _setup(hass, patch_api)
    eid = _eid(hass, f"{PHONE}_sim_block")
    assert eid is not None
    assert hass.states.get(eid).state == "off"
    await hass.services.async_call("switch", "turn_on", {"entity_id": eid}, blocking=True)
    patch_api.set_status.assert_called_with("SUSPENDED")


async def test_sim_block_switch_slave(hass: HomeAssistant, patch_api):
    patch_api.get_slaves.return_value = [{"msisdn": "79001112233"}]
    await _setup(hass, patch_api)
    eid = _eid(hass, "79001112233_sim_block")
    assert eid is not None
    await hass.services.async_call("switch", "turn_on", {"entity_id": eid}, blocking=True)
    patch_api.set_status.assert_called_with("SUSPENDED", subscriber="79001112233")
