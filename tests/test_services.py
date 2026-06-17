"""Tests for Tele2 services."""
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry
from tele2api import Tele2ApiError, Tele2LotError

from custom_components.tele2.const import (
    CONF_ACCESS_TOKEN,
    CONF_PHONE,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)


async def _setup(hass, patch_api):
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
    device = dr.async_get(hass).async_get_device({(DOMAIN, "79991234567")})
    return entry, device.id


async def test_create_lot_service(hass: HomeAssistant, patch_api):
    patch_api.create_lot.return_value = "LOT-123"
    _, device_id = await _setup(hass, patch_api)
    result = await hass.services.async_call(
        DOMAIN, "create_lot",
        {"device_id": device_id, "traffic_type": "voice", "value": 50, "amount": 40},
        blocking=True, return_response=True,
    )
    patch_api.create_lot.assert_called_once_with("voice", 50, 40, "None")
    assert result["lot_id"] == "LOT-123"


async def test_premium_lot_service(hass: HomeAssistant, patch_api):
    _, device_id = await _setup(hass, patch_api)
    await hass.services.async_call(
        DOMAIN, "premium_lot", {"device_id": device_id, "lot_id": "L1"},
        blocking=True,
    )
    patch_api.premium_lot.assert_called_once_with("L1")


async def test_service_error_raises(hass: HomeAssistant, patch_api):
    patch_api.premium_lot.side_effect = Tele2LotError("LOT_NOT_FOUND")
    _, device_id = await _setup(hass, patch_api)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "premium_lot", {"device_id": device_id, "lot_id": "bad"},
            blocking=True,
        )


# --- Bulk: premium_all delegates to the library helper ----------------------


async def test_premium_all_lots_boosts_each(hass: HomeAssistant, patch_api):
    patch_api.premium_all_lots.return_value = {
        "ok": ["L1", "L2", "L3"], "failed": [], "errors": {},
    }
    _, device_id = await _setup(hass, patch_api)
    result = await hass.services.async_call(
        DOMAIN, "premium_all_lots", {"device_id": device_id},
        blocking=True, return_response=True,
    )
    patch_api.premium_all_lots.assert_called_once_with(traffic_type=None)
    assert result["boosted"] == 3
    assert result["failed"] == 0


async def test_premium_all_lots_filters_by_traffic_type(hass: HomeAssistant, patch_api):
    patch_api.premium_all_lots.return_value = {"ok": ["L1"], "failed": [], "errors": {}}
    _, device_id = await _setup(hass, patch_api)
    result = await hass.services.async_call(
        DOMAIN, "premium_all_lots",
        {"device_id": device_id, "traffic_type": "voice"},
        blocking=True, return_response=True,
    )
    patch_api.premium_all_lots.assert_called_once_with(traffic_type="voice")
    assert result["boosted"] == 1


async def test_premium_all_lots_partial_failure(hass: HomeAssistant, patch_api):
    patch_api.premium_all_lots.return_value = {
        "ok": ["L1"], "failed": ["BAD"], "errors": {"BAD": "LOT_NOT_FOUND"},
    }
    _, device_id = await _setup(hass, patch_api)
    result = await hass.services.async_call(
        DOMAIN, "premium_all_lots", {"device_id": device_id},
        blocking=True, return_response=True,
    )
    assert result["boosted"] == 1
    assert result["failed"] == 1
    assert result["errors"][0]["lot_id"] == "BAD"


async def test_premium_all_lots_surfaces_fetch_error(hass: HomeAssistant, patch_api):
    """An error fetching active lots is reported, not silently swallowed."""
    patch_api.premium_all_lots.side_effect = Tele2ApiError("SOME_ERROR")
    _, device_id = await _setup(hass, patch_api)
    result = await hass.services.async_call(
        DOMAIN, "premium_all_lots", {"device_id": device_id},
        blocking=True, return_response=True,
    )
    assert result["boosted"] == 0
    assert result["errors"]
    assert result["errors"][0]["error"] == "SOME_ERROR"


async def test_premium_all_lots_empty(hass: HomeAssistant, patch_api):
    patch_api.premium_all_lots.return_value = {"ok": [], "failed": [], "errors": {}}
    _, device_id = await _setup(hass, patch_api)
    result = await hass.services.async_call(
        DOMAIN, "premium_all_lots", {"device_id": device_id},
        blocking=True, return_response=True,
    )
    assert result["boosted"] == 0
    assert result["failed"] == 0


# --- Bulk: delete_all / create_lots delegate too ----------------------------


async def test_delete_all_lots_deletes_each(hass: HomeAssistant, patch_api):
    patch_api.delete_all_lots.return_value = {"ok": ["L1", "L2"], "failed": [], "errors": {}}
    _, device_id = await _setup(hass, patch_api)
    result = await hass.services.async_call(
        DOMAIN, "delete_all_lots", {"device_id": device_id},
        blocking=True, return_response=True,
    )
    patch_api.delete_all_lots.assert_called_once_with(traffic_type=None)
    assert result["deleted"] == 2
    assert result["failed"] == 0


async def test_delete_all_lots_filters_by_traffic_type(hass: HomeAssistant, patch_api):
    patch_api.delete_all_lots.return_value = {"ok": ["L1"], "failed": [], "errors": {}}
    _, device_id = await _setup(hass, patch_api)
    result = await hass.services.async_call(
        DOMAIN, "delete_all_lots",
        {"device_id": device_id, "traffic_type": "voice"},
        blocking=True, return_response=True,
    )
    patch_api.delete_all_lots.assert_called_once_with(traffic_type="voice")
    assert result["deleted"] == 1


async def test_delete_all_lots_partial_failure(hass: HomeAssistant, patch_api):
    patch_api.delete_all_lots.return_value = {
        "ok": ["L1"], "failed": ["L2"], "errors": {"L2": "LOT_NOT_FOUND"},
    }
    _, device_id = await _setup(hass, patch_api)
    result = await hass.services.async_call(
        DOMAIN, "delete_all_lots", {"device_id": device_id},
        blocking=True, return_response=True,
    )
    assert result["deleted"] == 1
    assert result["failed"] == 1
    assert result["errors"][0]["lot_id"] == "L2"


async def test_create_lots_creates_each(hass: HomeAssistant, patch_api):
    patch_api.create_lots.return_value = {"ok": ["LOT-A", "LOT-B"], "failed": [], "errors": {}}
    _, device_id = await _setup(hass, patch_api)
    result = await hass.services.async_call(
        DOMAIN, "create_lots",
        {"device_id": device_id, "traffic_type": "voice",
         "volumes": [50, 30], "amount": 40},
        blocking=True, return_response=True,
    )
    patch_api.create_lots.assert_called_once_with("voice", [50, 30], 40, "None")
    assert result["created"] == ["LOT-A", "LOT-B"]
    assert result["failed"] == 0


async def test_create_lots_partial_failure(hass: HomeAssistant, patch_api):
    patch_api.create_lots.return_value = {
        "ok": ["LOT-A"], "failed": [30], "errors": {30: "LOT_LIMIT"},
    }
    _, device_id = await _setup(hass, patch_api)
    result = await hass.services.async_call(
        DOMAIN, "create_lots",
        {"device_id": device_id, "traffic_type": "voice",
         "volumes": [50, 30], "amount": 40},
        blocking=True, return_response=True,
    )
    assert result["created"] == ["LOT-A"]
    assert result["failed"] == 1
    assert result["errors"][0]["volume"] == 30


# --- Demping (undercut): delegate to the library helper ---------------------

_LOT = {"id": "L1", "trafficType": "voice", "volume": {"value": 50}, "cost": {"amount": 100}}


async def test_undercut_lot_lowers_price(hass: HomeAssistant, patch_api):
    patch_api.get_active_lots.return_value = [dict(_LOT)]
    patch_api.undercut_lot.return_value = {
        "changed": True, "old_price": 100, "new_price": 89, "reason": "undercut",
    }
    _, device_id = await _setup(hass, patch_api)
    result = await hass.services.async_call(
        DOMAIN, "undercut_lot", {"device_id": device_id, "lot_id": "L1"},
        blocking=True, return_response=True,
    )
    patch_api.undercut_lot.assert_called_once_with(_LOT, 1, 1)
    assert result["changed"] is True
    assert result["new_price"] == 89
    assert result["lot_id"] == "L1"


async def test_undercut_lot_not_found(hass: HomeAssistant, patch_api):
    patch_api.get_active_lots.return_value = [dict(_LOT)]
    _, device_id = await _setup(hass, patch_api)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "undercut_lot", {"device_id": device_id, "lot_id": "NOPE"},
            blocking=True, return_response=True,
        )
    patch_api.undercut_lot.assert_not_called()


async def test_undercut_lot_passes_min_amount(hass: HomeAssistant, patch_api):
    patch_api.get_active_lots.return_value = [dict(_LOT)]
    patch_api.undercut_lot.return_value = {
        "changed": True, "old_price": 100, "new_price": 10, "reason": "undercut",
    }
    _, device_id = await _setup(hass, patch_api)
    result = await hass.services.async_call(
        DOMAIN, "undercut_lot",
        {"device_id": device_id, "lot_id": "L1", "min_amount": 10},
        blocking=True, return_response=True,
    )
    patch_api.undercut_lot.assert_called_once_with(_LOT, 1, 10)
    assert result["new_price"] == 10


async def test_undercut_all_lots(hass: HomeAssistant, patch_api):
    patch_api.undercut_all_lots.return_value = [
        {"changed": True, "old_price": 100, "new_price": 79, "lot_id": "L1"},
    ]
    _, device_id = await _setup(hass, patch_api)
    result = await hass.services.async_call(
        DOMAIN, "undercut_all_lots", {"device_id": device_id},
        blocking=True, return_response=True,
    )
    patch_api.undercut_all_lots.assert_called_once_with(1, 1, None)
    assert result["changed"] == 1


# --- Per-number targeting ----------------------------------------------------


async def _setup_with_slave(hass, patch_api, slave="79001112233"):
    patch_api.get_slaves.return_value = [{"msisdn": slave, "state": "active"}]
    entry, master_device_id = await _setup(hass, patch_api)
    slave_device = dr.async_get(hass).async_get_device({(DOMAIN, slave)})
    return entry, master_device_id, slave_device.id


async def test_set_status_targets_slave(hass: HomeAssistant, patch_api):
    _, _, slave_id = await _setup_with_slave(hass, patch_api)
    await hass.services.async_call(
        DOMAIN, "set_status",
        {"device_id": slave_id, "status": "SUSPENDED"},
        blocking=True,
    )
    patch_api.set_status.assert_called_with("SUSPENDED", subscriber="79001112233")


async def test_set_status_master_has_no_subscriber(hass: HomeAssistant, patch_api):
    _, master_id = await _setup(hass, patch_api)
    await hass.services.async_call(
        DOMAIN, "set_status",
        {"device_id": master_id, "status": "ACTIVATED"},
        blocking=True,
    )
    patch_api.set_status.assert_called_with("ACTIVATED")


async def test_connect_service(hass: HomeAssistant, patch_api):
    _, device_id = await _setup(hass, patch_api)
    await hass.services.async_call(
        DOMAIN, "connect_service",
        {"device_id": device_id, "billing_id": "46556"},
        blocking=True,
    )
    patch_api.connect_service.assert_called_once_with("46556")
