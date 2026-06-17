"""Switch platform for the Tele2 integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from tele2api import Tele2ApiError

from .const import DOMAIN
from .coordinator import SubscriberData, Tele2Coordinator


def _can_disconnect(svc: dict) -> bool:
    """Whether t2 actually allows disconnecting this service.

    Most connected services are tariff-bundled and non-removable; a DELETE on
    them returns ``UNKNOWN_ERROR`` (``err_service_command_not_allowed``). Only
    expose a switch for services the API marks as disconnectable.
    """
    status = svc.get("disconnectionAvailabilityStatus")
    return isinstance(status, dict) and status.get("canDisconnect") is True


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tele2 switches."""
    coordinator = hass.data[DOMAIN][entry.entry_id].coordinator
    data = coordinator.data
    master = data.master
    entities: list[CoordinatorEntity] = []

    for msisdn in data.subscribers:
        entities.append(Tele2SimBlockSwitch(coordinator, msisdn, master))

    master_sub = data.subscribers.get(master)
    if master_sub is not None:
        if master_sub.mixx_enabled is not None:
            entities.append(Tele2MixxSwitch(coordinator, master))
        for svc in master_sub.services:
            billing_id = svc.get("billingId")
            if billing_id and _can_disconnect(svc):
                entities.append(Tele2ServiceSwitch(coordinator, master, str(billing_id)))

    async_add_entities(entities)


class _Tele2SwitchBase(CoordinatorEntity[Tele2Coordinator], SwitchEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: Tele2Coordinator, msisdn: str, master: str) -> None:
        super().__init__(coordinator)
        self._msisdn = msisdn
        info = DeviceInfo(
            identifiers={(DOMAIN, msisdn)},
            name=f"t2 {msisdn}",
            manufacturer="t2 (Tele2)",
        )
        if msisdn != master:
            info["via_device"] = (DOMAIN, master)
        self._attr_device_info = info

    @property
    def _sub(self) -> SubscriberData | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.subscribers.get(self._msisdn)

    async def _apply(self, method: str, *args: Any, **kwargs: Any) -> None:
        """Run a write, then refresh real state BEFORE raising on error.

        Refreshing first means the entity reflects the actual t2 state even when
        the write fails — otherwise the frontend keeps the optimistic toggle
        position until a manual reload.
        """
        try:
            await self.coordinator.client.async_call(method, *args, **kwargs)
        except Tele2ApiError as err:
            await self.coordinator.async_request_refresh()
            raise HomeAssistantError(f"t2 API error: {err}") from err
        await self.coordinator.async_request_refresh()


class Tele2SimBlockSwitch(_Tele2SwitchBase):
    """Block/unblock a number's SIM (on == SUSPENDED)."""

    _attr_translation_key = "sim_block"
    _attr_icon = "mdi:sim-off"

    def __init__(self, coordinator: Tele2Coordinator, msisdn: str, master: str) -> None:
        super().__init__(coordinator, msisdn, master)
        self._attr_unique_id = f"{msisdn}_sim_block"
        self._master = master

    @property
    def available(self) -> bool:
        return super().available and self._sub is not None

    @property
    def is_on(self) -> bool | None:
        sub = self._sub
        return None if sub is None else sub.status == "SUSPENDED"

    async def _set(self, status: str) -> None:
        kwargs = {} if self._msisdn == self._master else {"subscriber": self._msisdn}
        await self._apply("set_status", status, **kwargs)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set("SUSPENDED")

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set("ACTIVATED")


class Tele2MixxSwitch(_Tele2SwitchBase):
    """Toggle the account's MiXX subscription."""

    _attr_translation_key = "mixx"
    _attr_icon = "mdi:music-box-multiple"

    def __init__(self, coordinator: Tele2Coordinator, master: str) -> None:
        super().__init__(coordinator, master, master)
        self._attr_unique_id = f"{master}_mixx"

    @property
    def is_on(self) -> bool | None:
        sub = self._sub
        return None if sub is None else sub.mixx_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._apply("mixx_update_subscribe", "enable")

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._apply("mixx_update_subscribe", "disable")


class Tele2ServiceSwitch(_Tele2SwitchBase):
    """Connect/disconnect a single account service by billingId."""

    def __init__(self, coordinator: Tele2Coordinator, master: str, billing_id: str) -> None:
        super().__init__(coordinator, master, master)
        self._billing_id = billing_id
        self._attr_unique_id = f"{master}_service_{billing_id}"

    def _service(self) -> dict | None:
        sub = self._sub
        if sub is None:
            return None
        for svc in sub.services:
            if str(svc.get("billingId")) == self._billing_id:
                return svc
        return None

    @property
    def name(self) -> str | None:
        svc = self._service()
        return svc.get("name") if svc else f"Service {self._billing_id}"

    @property
    def is_on(self) -> bool:
        return self._service() is not None

    @property
    def extra_state_attributes(self) -> dict | None:
        svc = self._service()
        if svc is None:
            return None
        fee = svc.get("abonentFee")
        amount = fee.get("amount") if isinstance(fee, dict) else None
        return {
            "billing_id": self._billing_id,
            "abonent_fee": amount,
            "paid": bool(amount) and not svc.get("free"),
            "category": svc.get("category"),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._apply("connect_service", self._billing_id)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._apply("disconnect_service", self._billing_id)
