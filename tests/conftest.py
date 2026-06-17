"""Fixtures for Tele2 tests."""
import sys
from unittest.mock import MagicMock, patch

import pytest

# On Windows, asyncio's event-loop self-pipe is emulated with an AF_INET
# socketpair, which pytest-homeassistant-custom-component's `disable_socket`
# blocks (it only whitelists AF_UNIX). Neutralize the block on Windows dev
# machines; tests fully mock the t2 API, so no real network access occurs.
if sys.platform == "win32":
    import pytest_socket

    pytest_socket.disable_socket = lambda *args, **kwargs: None

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in all tests."""
    yield


@pytest.fixture
def mock_api():
    """A MagicMock standing in for tele2api.Tele2Api."""
    api = MagicMock()
    api.access_token = "header.eyJleHAiOjk5OTk5OTk5OTl9.sig"  # exp far future
    api.refresh_token = "refresh-token"
    api.is_token_expired.return_value = False  # token fresh; no refresh by default
    api.get_balance.return_value = 251.4
    api.get_rests.return_value = {"data": 30, "voice": 600, "sms": 0}
    api.get_rests_rollover.return_value = {"data": 0, "voice": 0, "sms": 0}
    api.get_status.return_value = "ACTIVATED"
    api.get_tariff.return_value = {"frontName": "Мой онлайн", "abonentFee": 400}
    api.get_charges.return_value = []
    api.get_rests_detailed.return_value = []
    api.get_slaves.return_value = []
    api.get_active_lots.return_value = []
    api.get_lot_position.return_value = []
    api.update_token.return_value = ("new-access", "new-refresh")
    api.get_services.return_value = []
    api.mixx_update_subscribe.return_value = "OK"
    api.connect_service.return_value = "OK"
    api.disconnect_service.return_value = "OK"
    api.set_status.return_value = "OK"
    return api


@pytest.fixture
def patch_api(mock_api):
    """Patch Tele2Api constructor everywhere it is imported."""
    with patch("custom_components.tele2.Tele2Api", return_value=mock_api), \
         patch("custom_components.tele2.client.Tele2Api", return_value=mock_api), \
         patch("custom_components.tele2.config_flow.Tele2Api", return_value=mock_api):
        yield mock_api
