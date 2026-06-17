"""Async wrapper around the synchronous tele2api client."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from functools import partial
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant

from tele2api import Tele2Api, Tele2AuthError

from .const import CONF_ACCESS_TOKEN, CONF_REFRESH_TOKEN, TOKEN_REFRESH_MARGIN

_LOGGER = logging.getLogger(__name__)


class Tele2Client:
    """Thin async facade over tele2api.Tele2Api with token refresh."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: Tele2Api,
        entry: ConfigEntry | None = None,
    ) -> None:
        self._hass = hass
        self._api = api
        self._entry = entry
        self._lock = asyncio.Lock()

    @property
    def access_token(self) -> str:
        return self._api.access_token

    @property
    def refresh_token(self) -> str:
        return self._api.refresh_token

    async def _run(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        return await self._hass.async_add_executor_job(partial(func, *args, **kwargs))

    async def async_refresh_token(self) -> None:
        """Refresh the access token and persist the new pair.

        ``update_token`` raises ``Tele2AuthError`` when the refresh token is
        dead; surface it as ``ConfigEntryAuthFailed`` so HA starts the reauth
        flow.
        """
        async with self._lock:
            try:
                access, refresh = await self._run(self._api.update_token)
            except Tele2AuthError as err:
                raise ConfigEntryAuthFailed(f"Token refresh failed: {err}") from err
            if self._entry is not None:
                self._hass.config_entries.async_update_entry(
                    self._entry,
                    data={
                        **self._entry.data,
                        CONF_ACCESS_TOKEN: access,
                        CONF_REFRESH_TOKEN: refresh,
                    },
                )

    async def async_ensure_token(self) -> None:
        """Refresh the token if it is missing or about to expire."""
        if self._api.is_token_expired(TOKEN_REFRESH_MARGIN):
            await self.async_refresh_token()

    async def async_call(self, method_name: str, *args, **kwargs) -> Any:
        """Ensure a valid token, then run the named api method in the executor.

        Any ``Tele2AuthError`` — from the proactive refresh or a 401 raised by
        the call itself — becomes ``ConfigEntryAuthFailed`` so the single auth
        path covers the coordinator, services and switches alike.
        """
        try:
            await self.async_ensure_token()
            func = getattr(self._api, method_name)
            return await self._run(func, *args, **kwargs)
        except Tele2AuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
