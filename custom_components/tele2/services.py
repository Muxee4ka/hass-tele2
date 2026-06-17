"""Tele2 services."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import voluptuous as vol
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from tele2api import Tele2ApiError

from .client import Tele2Client
from .const import DOMAIN, EMOJIS, TRAFFIC_TYPES


@dataclass
class _Target:
    """A resolved Tele2 account plus the number a call should address.

    ``msisdn`` is ``None`` for the master (calls stay identical to the
    single-number behaviour) and the slave number otherwise.
    """

    client: Tele2Client
    coordinator: Any
    msisdn: str | None

    async def call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        if self.msisdn is not None:
            kwargs["subscriber"] = self.msisdn
        return await self.client.async_call(method, *args, **kwargs)


def _resolve_target(hass: HomeAssistant, call: ServiceCall) -> "_Target":
    """Resolve the targeted device to (client, coordinator, msisdn)."""
    device_ids = call.data.get(ATTR_DEVICE_ID)
    runtime_map = hass.data[DOMAIN]
    if device_ids:
        device_id = device_ids[0] if isinstance(device_ids, list) else device_ids
        device = dr.async_get(hass).async_get(device_id)
        if device is None:
            raise HomeAssistantError(f"Unknown device {device_id}")
        msisdn = next(
            (ident[1] for ident in device.identifiers if ident[0] == DOMAIN), None
        )
        for entry_id in device.config_entries:
            if entry_id in runtime_map:
                runtime = runtime_map[entry_id]
                master = runtime.coordinator.master
                sub = None if msisdn in (None, master) else msisdn
                return _Target(runtime.client, runtime.coordinator, sub)
        raise HomeAssistantError("Device is not a Tele2 account")
    if len(runtime_map) == 1:
        runtime = next(iter(runtime_map.values()))
        return _Target(runtime.client, runtime.coordinator, None)
    raise HomeAssistantError("Specify a target device (multiple accounts configured)")


def async_setup_services(hass: HomeAssistant) -> None:
    """Register Tele2 services (idempotent)."""
    if hass.services.has_service(DOMAIN, "create_lot"):
        return

    async def _refresh(target: "_Target") -> None:
        await target.coordinator.async_request_refresh()

    async def _call(target: "_Target", method: str, *args: Any, **kwargs: Any) -> Any:
        """Run a write, mapping API errors to HomeAssistantError."""
        try:
            return await target.call(method, *args, **kwargs)
        except Tele2ApiError as err:
            raise HomeAssistantError(f"t2 API error: {err}") from err

    async def create_lot(call: ServiceCall) -> ServiceResponse:
        target = _resolve_target(hass, call)
        lot_id = await _call(
            target,
            "create_lot",
            call.data["traffic_type"],
            call.data["value"],
            call.data["amount"],
            call.data.get("emojis", "None"),
        )
        await _refresh(target)
        return {"lot_id": lot_id}

    async def patch_lot(call: ServiceCall) -> None:
        target = _resolve_target(hass, call)
        await _call(target, "patch_lot", call.data["lot_id"], call.data["amount"])
        await _refresh(target)

    async def premium_lot(call: ServiceCall) -> None:
        target = _resolve_target(hass, call)
        await _call(target, "premium_lot", call.data["lot_id"])
        await _refresh(target)

    async def delete_lot(call: ServiceCall) -> None:
        target = _resolve_target(hass, call)
        await _call(target, "delete_lot", call.data["lot_id"])
        await _refresh(target)

    async def set_status(call: ServiceCall) -> None:
        target = _resolve_target(hass, call)
        await _call(target, "set_status", call.data["status"])
        await _refresh(target)

    async def refresh(call: ServiceCall) -> None:
        target = _resolve_target(hass, call)
        await _refresh(target)

    async def connect_service(call: ServiceCall) -> None:
        target = _resolve_target(hass, call)
        # services are account-level: never pass a subscriber
        try:
            await target.client.async_call("connect_service", call.data["billing_id"])
        except Tele2ApiError as err:
            raise HomeAssistantError(f"t2 API error: {err}") from err
        await _refresh(target)

    async def premium_all_lots(call: ServiceCall) -> ServiceResponse:
        target = _resolve_target(hass, call)
        try:
            res = await target.call(
                "premium_all_lots", traffic_type=call.data.get("traffic_type")
            )
        except Tele2ApiError as err:
            return {"boosted": 0, "failed": 0, "errors": [{"error": str(err)}]}
        await _refresh(target)
        return {
            "boosted": len(res["ok"]),
            "failed": len(res["failed"]),
            "errors": [{"lot_id": k, "error": v} for k, v in res["errors"].items()],
        }

    async def delete_all_lots(call: ServiceCall) -> ServiceResponse:
        target = _resolve_target(hass, call)
        try:
            res = await target.call(
                "delete_all_lots", traffic_type=call.data.get("traffic_type")
            )
        except Tele2ApiError as err:
            return {"deleted": 0, "failed": 0, "errors": [{"error": str(err)}]}
        await _refresh(target)
        return {
            "deleted": len(res["ok"]),
            "failed": len(res["failed"]),
            "errors": [{"lot_id": k, "error": v} for k, v in res["errors"].items()],
        }

    async def create_lots(call: ServiceCall) -> ServiceResponse:
        target = _resolve_target(hass, call)
        try:
            res = await target.call(
                "create_lots",
                call.data["traffic_type"],
                call.data["volumes"],
                call.data["amount"],
                call.data.get("emojis", "None"),
            )
        except Tele2ApiError as err:
            return {"created": [], "failed": 0, "errors": [{"error": str(err)}]}
        await _refresh(target)
        return {
            "created": res["ok"],
            "failed": len(res["failed"]),
            "errors": [{"volume": k, "error": v} for k, v in res["errors"].items()],
        }

    async def undercut_lot(call: ServiceCall) -> ServiceResponse:
        target = _resolve_target(hass, call)
        try:
            lots = await target.call("get_active_lots")
            lot = next((l for l in lots if l.get("id") == call.data["lot_id"]), None)
            if lot is None:
                raise HomeAssistantError("Lot not found among active lots")
            result = await target.call(
                "undercut_lot", lot, call.data["step"], call.data["min_amount"]
            )
        except Tele2ApiError as err:
            raise HomeAssistantError(f"t2 API error: {err}") from err
        result["lot_id"] = call.data["lot_id"]
        await _refresh(target)
        return result

    async def undercut_all_lots(call: ServiceCall) -> ServiceResponse:
        target = _resolve_target(hass, call)
        try:
            results = await target.call(
                "undercut_all_lots",
                call.data["step"],
                call.data["min_amount"],
                call.data.get("traffic_type"),
            )
        except Tele2ApiError as err:
            return {"changed": 0, "results": [], "errors": [{"error": str(err)}]}
        await _refresh(target)
        return {
            "changed": sum(1 for r in results if r.get("changed")),
            "results": results,
        }

    device_field = {vol.Optional(ATTR_DEVICE_ID): vol.Any(cv.string, [cv.string])}

    hass.services.async_register(
        DOMAIN, "create_lot", create_lot,
        schema=vol.Schema({
            **device_field,
            vol.Required("traffic_type"): vol.In(TRAFFIC_TYPES),
            vol.Required("value"): vol.Coerce(int),
            vol.Required("amount"): vol.Coerce(int),
            vol.Optional("emojis", default="None"): vol.Any(
                "None", "random", [vol.In(EMOJIS)]
            ),
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "undercut_lot", undercut_lot,
        schema=vol.Schema({
            **device_field,
            vol.Required("lot_id"): cv.string,
            vol.Optional("step", default=1): vol.Coerce(int),
            vol.Optional("min_amount", default=1): vol.Coerce(int),
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "undercut_all_lots", undercut_all_lots,
        schema=vol.Schema({
            **device_field,
            vol.Optional("traffic_type"): vol.In(TRAFFIC_TYPES),
            vol.Optional("step", default=1): vol.Coerce(int),
            vol.Optional("min_amount", default=1): vol.Coerce(int),
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "patch_lot", patch_lot,
        schema=vol.Schema({
            **device_field,
            vol.Required("lot_id"): cv.string,
            vol.Required("amount"): vol.Coerce(int),
        }),
    )
    hass.services.async_register(
        DOMAIN, "premium_lot", premium_lot,
        schema=vol.Schema({**device_field, vol.Required("lot_id"): cv.string}),
    )
    hass.services.async_register(
        DOMAIN, "delete_lot", delete_lot,
        schema=vol.Schema({**device_field, vol.Required("lot_id"): cv.string}),
    )
    hass.services.async_register(
        DOMAIN, "set_status", set_status,
        schema=vol.Schema({
            **device_field,
            vol.Required("status"): vol.In(["ACTIVATED", "SUSPENDED"]),
        }),
    )
    hass.services.async_register(
        DOMAIN, "refresh", refresh,
        schema=vol.Schema(device_field),
    )
    hass.services.async_register(
        DOMAIN, "premium_all_lots", premium_all_lots,
        schema=vol.Schema({
            **device_field,
            vol.Optional("traffic_type"): vol.In(TRAFFIC_TYPES),
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "delete_all_lots", delete_all_lots,
        schema=vol.Schema({
            **device_field,
            vol.Optional("traffic_type"): vol.In(TRAFFIC_TYPES),
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "create_lots", create_lots,
        schema=vol.Schema({
            **device_field,
            vol.Required("traffic_type"): vol.In(TRAFFIC_TYPES),
            vol.Required("volumes"): [vol.Coerce(int)],
            vol.Required("amount"): vol.Coerce(int),
            vol.Optional("emojis", default="None"): vol.Any(
                "None", "random", [vol.In(EMOJIS)]
            ),
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "connect_service", connect_service,
        schema=vol.Schema({**device_field, vol.Required("billing_id"): cv.string}),
    )
