"""Data update coordinator for the Tele2 integration."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable

from homeassistant.config_entries import ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .client import Tele2Client
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _is_connected(svc: dict) -> bool:
    """A service the account currently has.

    The reliable signal is ``status == "CONNECTED"``. ``showDisconnectButton`` is
    not — t2 sets it on most AVAILABLE options too (a UI quirk), which would turn
    the whole ~100-entry catalogue into switches.
    """
    return isinstance(svc, dict) and svc.get("status") == "CONNECTED"


def _mixx_state(services: list) -> bool | None:
    """MiXX on/off derived from the catalogue; None if no MiXX entry exists."""
    for svc in services:
        if not isinstance(svc, dict):
            continue
        text = f"{svc.get('name', '')} {svc.get('slug', '')}".lower()
        if "mixx" in text or "микс" in text:
            return _is_connected(svc)
    return None


@dataclass
class SubscriberData:
    """Snapshot of one subscriber (master or slave) for one refresh cycle."""

    msisdn: str
    is_master: bool = False
    balance: float | None = None
    rests: dict = field(default_factory=dict)
    rollover: dict = field(default_factory=dict)
    status: str = ""
    tariff: dict = field(default_factory=dict)
    profile: dict = field(default_factory=dict)
    charges: list = field(default_factory=list)
    rests_detailed: list = field(default_factory=list)
    slaves: list = field(default_factory=list)
    lots: list[dict] = field(default_factory=list)
    services: list = field(default_factory=list)
    mixx_enabled: bool | None = None


@dataclass
class Tele2Data:
    """All subscribers for the account, keyed by msisdn."""

    master: str
    subscribers: dict[str, SubscriberData] = field(default_factory=dict)


class Tele2Coordinator(DataUpdateCoordinator[Tele2Data]):
    """Fetch all subscribers on the account in one cycle."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: Tele2Client,
        scan_interval: int,
        master: str,
        boost_interval: int = 15,
        boost_cost: float = 5,
        manage_slaves: bool = True,
        slave_market: bool = False,
        manage_services: bool = True,
    ) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        self.master = master
        self.boost_interval = boost_interval
        self.boost_cost = boost_cost
        self.manage_slaves = manage_slaves
        self.slave_market = slave_market
        self.manage_services = manage_services

    async def _async_update_data(self) -> Tele2Data:
        slaves_raw: list = []
        if self.manage_slaves:
            slaves_raw = await self._safe("get_slaves") or []
            if not isinstance(slaves_raw, list):
                slaves_raw = []
        msisdns = [self.master] + [
            s["msisdn"] for s in slaves_raw
            if isinstance(s, dict) and s.get("msisdn") and s["msisdn"] != self.master
        ]
        subscribers: dict[str, SubscriberData] = {}
        for msisdn in msisdns:
            is_master = msisdn == self.master
            subscribers[msisdn] = await self._fetch_subscriber(
                msisdn, is_master, slaves_raw if is_master else []
            )
        return Tele2Data(master=self.master, subscribers=subscribers)

    async def _fetch_subscriber(
        self, msisdn: str, is_master: bool, slaves: list
    ) -> SubscriberData:
        sd = SubscriberData(msisdn=msisdn, is_master=is_master, slaves=slaves)
        sub = None if is_master else msisdn

        async def grab(attr: str, method: str, *args: Any,
                       transform: Callable[[Any], Any] | None = None) -> None:
            value = await self._safe(method, *args, subscriber=sub)
            if value is None:
                return
            setattr(sd, attr, transform(value) if transform else value)

        await grab("balance", "get_balance")
        await grab("rests", "get_rests", transform=lambda v: v if isinstance(v, dict) else {})
        await grab("rollover", "get_rests_rollover", transform=lambda v: v if isinstance(v, dict) else {})
        await grab("status", "get_status", transform=lambda v: v if isinstance(v, str) else "")
        await grab("tariff", "get_tariff", transform=lambda v: v if isinstance(v, dict) else {})
        await grab("profile", "get_profile", transform=lambda v: v if isinstance(v, dict) else {})
        await grab("charges", "get_charges", transform=lambda v: v if isinstance(v, list) else [])
        await grab("rests_detailed", "get_rests_detailed", transform=lambda v: v if isinstance(v, list) else [])

        if is_master or self.slave_market:
            lots = await self._safe("get_active_lots", subscriber=sub)
            if isinstance(lots, list):
                lots = [dict(lot) for lot in lots if isinstance(lot, dict)]
                for lot in lots:
                    lot["position"] = await self._lot_position(lot, sub)
                    lot.update(self._lot_analytics(lot))
                sd.lots = lots

        if is_master and self.manage_services:
            catalogue = await self._safe("get_services")
            if isinstance(catalogue, list):
                sd.services = [s for s in catalogue if _is_connected(s)]
                sd.mixx_enabled = _mixx_state(catalogue)
        return sd

    async def _safe(self, method: str, *args: Any, subscriber: str | None = None) -> Any:
        """Call the api, isolating non-auth errors so one field/number can't
        fail the whole cycle. Auth failures propagate so HA can reauth."""
        kwargs = {} if subscriber is None else {"subscriber": subscriber}
        try:
            return await self.client.async_call(method, *args, **kwargs)
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:  # noqa: BLE001
            # Transient transport errors (curl timeouts / reset connections) are
            # expected and self-healing: the field keeps its previous value and
            # the next cycle retries. Log at DEBUG so they don't surface as
            # integration "errors" in the UI. Auth failures are re-raised above.
            _LOGGER.debug("t2 %s(%s) failed: %s", method, subscriber or "master", err)
            return None

    async def _lot_position(self, lot: dict, subscriber: str | None) -> int | None:
        listing = await self._safe(
            "get_lot_position", lot["trafficType"],
            lot["volume"]["value"], lot["cost"]["amount"], subscriber=subscriber,
        )
        if not isinstance(listing, list):
            return None
        for index, item in enumerate(listing):
            if item.get("id") == lot["id"]:
                return index + 1
        return None

    def _lot_analytics(self, lot: dict) -> dict:
        """Boost profitability for a lot (unchanged from the single-number version)."""
        cost = lot.get("cost")
        amount = cost.get("amount") if isinstance(cost, dict) else None
        if not isinstance(amount, (int, float)) or self.boost_interval <= 0:
            return {}
        cost_per_hour = (60 / self.boost_interval) * self.boost_cost
        if cost_per_hour <= 0:
            return {}
        return {
            "cost_per_hour": round(cost_per_hour, 2),
            "profitable_hours": round(amount / cost_per_hour, 1),
        }
