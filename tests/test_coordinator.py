"""Tests for Tele2Coordinator."""
import pytest
from homeassistant.config_entries import ConfigEntryAuthFailed
from tele2api import Tele2ApiError, Tele2AuthError

from custom_components.tele2.client import Tele2Client
from custom_components.tele2.coordinator import Tele2Coordinator

MASTER = "79991234567"


def _client(hass, api):
    return Tele2Client(hass, api)


def _coord(hass, api, **kw):
    return Tele2Coordinator(hass, _client(hass, api), 600, MASTER, **kw)


async def test_master_only_when_no_slaves(hass, mock_api):
    mock_api.get_slaves.return_value = []
    data = await _coord(hass, mock_api)._async_update_data()
    assert data.master == MASTER
    assert list(data.subscribers) == [MASTER]
    assert data.subscribers[MASTER].is_master is True
    assert data.subscribers[MASTER].balance == 251.4


async def test_discovers_slaves_as_subscribers(hass, mock_api):
    mock_api.get_slaves.return_value = [
        {"msisdn": "79001112233", "state": "active"},
        {"msisdn": "79004445566", "state": "active"},
    ]
    data = await _coord(hass, mock_api)._async_update_data()
    assert set(data.subscribers) == {MASTER, "79001112233", "79004445566"}
    assert data.subscribers["79001112233"].is_master is False
    assert len(data.subscribers[MASTER].slaves) == 2
    assert data.subscribers["79001112233"].slaves == []


async def test_slave_uses_subscriber_param(hass, mock_api):
    mock_api.get_slaves.return_value = [{"msisdn": "79001112233"}]
    await _coord(hass, mock_api)._async_update_data()
    mock_api.get_balance.assert_any_call(subscriber="79001112233")
    mock_api.get_balance.assert_any_call()


async def test_one_failing_slave_does_not_break_cycle(hass, mock_api):
    mock_api.get_slaves.return_value = [{"msisdn": "79001112233"}]

    def balance(subscriber=None):
        if subscriber == "79001112233":
            raise RuntimeError("403 for slave")
        return 251.4

    mock_api.get_balance.side_effect = balance
    data = await _coord(hass, mock_api)._async_update_data()
    assert data.subscribers[MASTER].balance == 251.4
    assert data.subscribers["79001112233"].balance is None


async def test_manage_slaves_off_skips_discovery(hass, mock_api):
    mock_api.get_slaves.return_value = [{"msisdn": "79001112233"}]
    data = await _coord(hass, mock_api, manage_slaves=False)._async_update_data()
    assert list(data.subscribers) == [MASTER]
    mock_api.get_slaves.assert_not_called()


async def test_slave_market_gated(hass, mock_api):
    mock_api.get_slaves.return_value = [{"msisdn": "79001112233"}]
    mock_api.get_active_lots.return_value = [
        {"id": "L1", "trafficType": "voice",
         "volume": {"value": 50}, "cost": {"amount": 40}}
    ]
    mock_api.get_lot_position.return_value = [{"id": "L1"}]
    data = await _coord(hass, mock_api)._async_update_data()
    assert data.subscribers["79001112233"].lots == []
    assert len(data.subscribers[MASTER].lots) == 1
    data = await _coord(hass, mock_api, slave_market=True)._async_update_data()
    assert len(data.subscribers["79001112233"].lots) == 1


async def test_auth_failure_propagates_for_reauth(hass, mock_api):
    """A dead refresh token raises Tele2AuthError → ConfigEntryAuthFailed."""
    mock_api.is_token_expired.return_value = True
    mock_api.update_token.side_effect = Tele2AuthError("invalid_grant")
    with pytest.raises(ConfigEntryAuthFailed):
        await _coord(hass, mock_api)._async_update_data()


async def test_data_auth_error_propagates_for_reauth(hass, mock_api):
    """A Tele2AuthError from a data call (401 mid-cycle) is not swallowed."""
    mock_api.get_slaves.return_value = []
    mock_api.get_balance.side_effect = Tele2AuthError("token rejected")
    with pytest.raises(ConfigEntryAuthFailed):
        await _coord(hass, mock_api)._async_update_data()


async def test_api_error_isolated_not_update_failed(hass, mock_api):
    mock_api.get_slaves.return_value = []
    mock_api.get_balance.side_effect = RuntimeError("network down")
    data = await _coord(hass, mock_api)._async_update_data()
    assert data.subscribers[MASTER].balance is None
    assert data.subscribers[MASTER].status == "ACTIVATED"


async def test_non_auth_api_error_isolated(hass, mock_api):
    """A non-auth Tele2ApiError on one field keeps the previous value, not reauth."""
    mock_api.get_slaves.return_value = []
    mock_api.get_balance.side_effect = Tele2ApiError("INTERNAL_ERROR")
    data = await _coord(hass, mock_api)._async_update_data()
    assert data.subscribers[MASTER].balance is None
    assert data.subscribers[MASTER].status == "ACTIVATED"


def _svc(billing_id, name, connected, fee=100.0, slug=""):
    return {
        "billingId": billing_id, "name": name, "slug": slug,
        "abonentFee": {"amount": fee, "period": "month"},
        "category": "internet",
        "showDisconnectButton": connected,
        "showConnectButton": not connected,
        "status": "CONNECTED" if connected else "AVAILABLE",
    }


async def test_master_services_connected_only(hass, mock_api):
    mock_api.get_services.return_value = [
        _svc("1", "Unlim weekends", True),
        _svc("2", "Some option", False),
    ]
    coordinator = Tele2Coordinator(hass, _client(hass, mock_api), 600, MASTER)
    data = await coordinator._async_update_data()
    master = data.subscribers[MASTER]
    assert [s["billingId"] for s in master.services] == ["1"]


async def test_mixx_state_derived(hass, mock_api):
    mock_api.get_services.return_value = [
        _svc("9", "Подписка MiXX", True, slug="mixx"),
    ]
    coordinator = Tele2Coordinator(hass, _client(hass, mock_api), 600, MASTER)
    data = await coordinator._async_update_data()
    assert data.subscribers[MASTER].mixx_enabled is True


async def test_mixx_state_unknown_when_absent(hass, mock_api):
    mock_api.get_services.return_value = [_svc("1", "X", True)]
    coordinator = Tele2Coordinator(hass, _client(hass, mock_api), 600, MASTER)
    data = await coordinator._async_update_data()
    assert data.subscribers[MASTER].mixx_enabled is None


async def test_manage_services_off_skips_fetch(hass, mock_api):
    coordinator = Tele2Coordinator(
        hass, _client(hass, mock_api), 600, MASTER, manage_services=False
    )
    data = await coordinator._async_update_data()
    assert data.subscribers[MASTER].services == []
    mock_api.get_services.assert_not_called()


async def test_slave_has_no_services(hass, mock_api):
    mock_api.get_slaves.return_value = [{"msisdn": "79001112233"}]
    mock_api.get_services.return_value = [_svc("1", "X", True)]
    coordinator = Tele2Coordinator(hass, _client(hass, mock_api), 600, MASTER)
    data = await coordinator._async_update_data()
    assert data.subscribers["79001112233"].services == []
