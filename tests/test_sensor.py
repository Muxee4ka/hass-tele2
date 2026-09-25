"""Tests for Tele2 sensors."""
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tele2.const import (
    CONF_ACCESS_TOKEN,
    CONF_PHONE,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)

PHONE = "79991234567"


async def _setup(hass, patch_api):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=PHONE,
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


def _state(hass, key):
    """Resolve a sensor state by its stable unique_id (`{phone}_{key}`)."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{PHONE}_{key}")
    assert entity_id is not None, f"sensor {key} not registered"
    return hass.states.get(entity_id)


async def test_balance_sensor(hass: HomeAssistant, patch_api):
    await _setup(hass, patch_api)
    state = _state(hass, "balance")
    assert state is not None
    assert state.state == "251.4"


async def test_data_remaining_sensor(hass: HomeAssistant, patch_api):
    await _setup(hass, patch_api)
    assert _state(hass, "data_remaining").state == "30"


async def test_monthly_charges_sensor(hass: HomeAssistant, patch_api):
    """Charges carry a nested {'amount': {'amount': N, 'currency': ..}} shape."""
    patch_api.get_charges.return_value = [
        {"amount": {"amount": 240.0, "currency": "RUB"}, "type": "VOICE"},
        {"amount": {"amount": 12.0, "currency": "RUB"}, "type": "SMS_MMS"},
    ]
    await _setup(hass, patch_api)
    assert _state(hass, "monthly_charges").state == "252.0"


async def test_rollover_enabled_by_default(hass: HomeAssistant, patch_api):
    """Rollover sensors are now enabled by default and have a state."""
    await _setup(hass, patch_api)
    state = _state(hass, "rollover_data")
    assert state is not None
    assert state.state == "0"


async def test_abonent_fee_uses_actual_charge(hass: HomeAssistant, patch_api):
    """Actual (discounted) fee comes from the SUBSCRIPTION_FEE charge, not the
    tariff list price; the list price is exposed as a base_fee attribute."""
    patch_api.get_tariff.return_value = {
        "frontName": "Мой онлайн+",
        "period": "month",
        "currentAbonentFee": {"amount": 800.0, "currency": "RUB"},
    }
    patch_api.get_charges.return_value = [
        {"type": "SUBSCRIPTION_FEE", "typeName": "Абонентская плата",
         "amount": {"amount": 240.0, "currency": "RUB"}},
    ]
    await _setup(hass, patch_api)
    state = _state(hass, "abonent_fee")
    assert state.state == "240.0"
    assert state.attributes["base_fee"] == 800.0
    assert state.attributes["period"] == "month"


async def test_abonent_fee_falls_back_to_list_price(hass: HomeAssistant, patch_api):
    """Before the fee is billed this month, fall back to the tariff list price."""
    patch_api.get_tariff.return_value = {
        "frontName": "Мой онлайн+",
        "currentAbonentFee": {"amount": 800.0, "currency": "RUB"},
    }
    patch_api.get_charges.return_value = []
    await _setup(hass, patch_api)
    assert _state(hass, "abonent_fee").state == "800.0"


async def test_package_renewal_sensor(hass: HomeAssistant, patch_api):
    """Earliest tariff-package endDay becomes a timestamp sensor."""
    patch_api.get_rests_detailed.return_value = [
        {"type": "tariff", "uom": "min", "remain": 600,
         "endDay": "2026-07-06T23:59:59.000+0300"},
        {"type": "tariff", "uom": "mb", "remain": 30720,
         "endDay": "2026-06-30T23:59:59.000+0300"},
        {"type": "service", "uom": "mb", "remain": 1, "endDay": None},
    ]
    await _setup(hass, patch_api)
    state = _state(hass, "package_renewal")
    # earliest of the two tariff dates, normalized to UTC ISO by HA
    assert state.state == "2026-06-30T20:59:59+00:00"


async def test_abonent_fee_prefers_tariff_cost(hass: HomeAssistant, patch_api):
    """Before billing, the discounted tariffCost beats the list price (issue #1)."""
    patch_api.get_tariff.return_value = {
        "frontName": "Мой онлайн+",
        "currentAbonentFee": {"amount": 850.0, "currency": "RUB"},
    }
    patch_api.get_charges.return_value = []
    patch_api.get_rests_detailed.return_value = [
        {"type": "service", "uom": "mb", "remain": 1,
         "tariffCost": {"amount": 1.0, "currency": "RUB"}},
        {"type": "tariff", "uom": "min", "remain": 600,
         "tariffCost": {"amount": 540.0, "currency": "RUB"}},
    ]
    await _setup(hass, patch_api)
    state = _state(hass, "abonent_fee")
    assert state.state == "540.0"
    assert state.attributes["base_fee"] == 850.0


async def test_package_renewal_prefers_renew_date(hass: HomeAssistant, patch_api):
    """service.renewDate (exact charge moment) wins over endDay; a package
    without renewDate still falls back to its endDay."""
    patch_api.get_rests_detailed.return_value = [
        {"type": "tariff", "uom": "min", "remain": 600,
         "endDay": "2026-09-25T23:59:59.000+0300",
         "service": {"renewDate": "2026-09-26T00:00:00.000+0300"}},
        {"type": "tariff", "uom": "mb", "remain": 30720,
         "endDay": "2026-09-27T23:59:59.000+0300", "service": {}},
    ]
    await _setup(hass, patch_api)
    state = _state(hass, "package_renewal")
    assert state.state == "2026-09-25T21:00:00+00:00"
    assert state.attributes["packages"][0]["renewDate"] == (
        "2026-09-26T00:00:00.000+0300"
    )
    assert state.attributes["packages"][1]["renewDate"] is None


async def test_linked_numbers_sensor(hass: HomeAssistant, patch_api):
    patch_api.get_slaves.return_value = [
        {"msisdn": "79001112233", "state": "active"},
        {"msisdn": "79004445566", "state": "active"},
    ]
    await _setup(hass, patch_api)
    state = _state(hass, "linked_numbers")
    assert state.state == "2"
    assert state.attributes["numbers"] == ["79001112233", "79004445566"]


async def test_tariff_abonent_fee_attr(hass: HomeAssistant, patch_api):
    """Abonent fee lives in nested currentAbonentFee.amount on real payloads."""
    patch_api.get_tariff.return_value = {
        "frontName": "Мой онлайн+",
        "currentAbonentFee": {"amount": 800.0, "currency": "RUB"},
    }
    await _setup(hass, patch_api)
    state = _state(hass, "tariff")
    assert state.state == "Мой онлайн+"
    assert state.attributes["abonent_fee"] == 800.0


async def test_active_lots_sensor(hass: HomeAssistant, patch_api):
    patch_api.get_active_lots.return_value = [
        {"id": "L1", "trafficType": "voice",
         "volume": {"value": 50, "uom": "min"},
         "cost": {"amount": 40, "currency": "rub"}}
    ]
    patch_api.get_lot_position.return_value = [{"id": "L1"}]
    await _setup(hass, patch_api)
    state = _state(hass, "active_lots")
    assert state.state == "1"
    assert state.attributes["lots"][0]["position"] == 1


def _state_for(hass, msisdn, key):
    """Resolve a sensor state by unique_id for any subscriber."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{msisdn}_{key}")
    assert entity_id is not None, f"sensor {msisdn}_{key} not registered"
    return hass.states.get(entity_id)


async def test_slave_creates_its_own_device(hass: HomeAssistant, patch_api):
    patch_api.get_slaves.return_value = [{"msisdn": "79001112233", "state": "active"}]
    await _setup(hass, patch_api)
    state = _state_for(hass, "79001112233", "balance")
    assert state is not None
    assert state.state == "251.4"


async def test_linked_numbers_only_on_master(hass: HomeAssistant, patch_api):
    patch_api.get_slaves.return_value = [{"msisdn": "79001112233"}]
    await _setup(hass, patch_api)
    assert _state_for(hass, "79991234567", "linked_numbers") is not None
    # slave should NOT have a linked_numbers sensor
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("sensor", DOMAIN, "79001112233_linked_numbers") is None


async def test_slave_device_links_to_master(hass: HomeAssistant, patch_api):
    from homeassistant.helpers import device_registry as dr

    patch_api.get_slaves.return_value = [{"msisdn": "79001112233"}]
    await _setup(hass, patch_api)
    reg = dr.async_get(hass)
    slave = reg.async_get_device({(DOMAIN, "79001112233")})
    master = reg.async_get_device({(DOMAIN, "79991234567")})
    assert slave is not None and master is not None
    assert slave.via_device_id == master.id


async def test_connected_services_sensor(hass: HomeAssistant, patch_api):
    patch_api.get_services.return_value = [
        {"billingId": "1", "name": "A", "abonentFee": {"amount": 100.0},
         "showDisconnectButton": True, "status": "CONNECTED"},
        {"billingId": "2", "name": "B", "abonentFee": {"amount": 50.0},
         "showDisconnectButton": True, "status": "CONNECTED"},
        {"billingId": "3", "name": "C", "showDisconnectButton": False},
    ]
    await _setup(hass, patch_api)
    state = _state(hass, "connected_services")
    assert state.state == "2"
    assert state.attributes["monthly_fee"] == 150.0
    assert state.attributes["paid_count"] == 2
    assert state.attributes["free_count"] == 0
    svc_a = next(s for s in state.attributes["services"] if s["billing_id"] == "1")
    assert svc_a["paid"] is True
    assert svc_a["removable"] is False
