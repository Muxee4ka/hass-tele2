"""Sensor platform for the Tele2 integration."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SubscriberData, Tele2Coordinator


def _money(value: Any, default: Any = None) -> Any:
    """Extract a numeric value from a t2 monetary field.

    t2 wraps money as ``{"amount": N, "currency": ".."}``; some payloads use a
    bare number. Returns ``default`` when no number is present.
    """
    if isinstance(value, dict):
        value = value.get("amount")
    return value if isinstance(value, (int, float)) else default


def _total_charges(charges: list) -> float:
    return round(
        sum(_money(c.get("amount"), 0) for c in charges if isinstance(c, dict)),
        2,
    )


# Charge ``type`` codes that get a dedicated category sensor. Anything t2 returns
# outside this set is summed into the "other" sensor, so no spend is ever lost.
# Confirmed against ~6 months of live data (calls/internet/roaming stay inside
# the bundle for this account and never surface as their own charge).
CHARGE_SUBSCRIPTION = "SUBSCRIPTION_FEE"
CHARGE_MESSAGES = "SMS_MMS"
CHARGE_CONTENT = "CONTENT"
KNOWN_CHARGE_TYPES = (CHARGE_SUBSCRIPTION, CHARGE_MESSAGES, CHARGE_CONTENT)


def _category_total(charges: list, *types: str) -> float:
    """Sum the month's charge amounts whose ``type`` is one of ``types``."""
    return round(
        sum(
            _money(c.get("amount"), 0)
            for c in charges
            if isinstance(c, dict) and c.get("type") in types
        ),
        2,
    )


def _other_total(charges: list) -> float:
    """Sum charges whose ``type`` has no dedicated category sensor."""
    return round(
        sum(
            _money(c.get("amount"), 0)
            for c in charges
            if isinstance(c, dict) and c.get("type") not in KNOWN_CHARGE_TYPES
        ),
        2,
    )


def _charge_line_items(charge: dict) -> list[dict]:
    """Flatten one charge's ``subGroups → consumingServices`` into name/amount."""
    items: list[dict] = []
    for group in charge.get("subGroups") or []:
        if not isinstance(group, dict):
            continue
        for svc in group.get("consumingServices") or []:
            if isinstance(svc, dict):
                items.append(
                    {
                        "name": svc.get("billingServiceName"),
                        "amount": _money(svc.get("amount"), 0),
                    }
                )
    return items


def _category_items(charges: list, *types: str) -> list[dict]:
    """Line items for the categories in ``types`` (the dedicated sensors)."""
    items: list[dict] = []
    for c in charges:
        if isinstance(c, dict) and c.get("type") in types:
            items += _charge_line_items(c)
    return items


def _other_items(charges: list) -> list[dict]:
    """Line items for every category without a dedicated sensor."""
    items: list[dict] = []
    for c in charges:
        if isinstance(c, dict) and c.get("type") not in KNOWN_CHARGE_TYPES:
            items += _charge_line_items(c)
    return items


def _charges_by_category(charges: list) -> list[dict]:
    """Full per-category summary for the month, including types without a sensor."""
    return [
        {
            "type": c.get("type"),
            "name": c.get("typeName"),
            "amount": _money(c.get("amount"), 0),
        }
        for c in charges
        if isinstance(c, dict)
    ]


def _base_fee(tariff: dict) -> Any:
    """The tariff list price (without personal discounts)."""
    return _money(tariff.get("currentAbonentFee") or tariff.get("abonentFee"))


def _tariff_cost(rests_detailed: list) -> Any:
    """Final (discounted) tariff price carried on the tariff package items."""
    for item in rests_detailed:
        if not isinstance(item, dict) or item.get("type") != "tariff":
            continue
        cost = _money(item.get("tariffCost"))
        if cost is not None:
            return cost
    return None


def _abonent_fee(data: SubscriberData) -> Any:
    """Subscription fee actually charged (reflects personal discounts).

    t2's tariff exposes only the list price. The real price is the
    ``tariffCost`` of the tariff packages (known before billing), then the
    ``SUBSCRIPTION_FEE`` charge once billed; the list price is the last resort.
    """
    cost = _tariff_cost(data.rests_detailed)
    if cost is not None:
        return cost
    for charge in data.charges:
        if isinstance(charge, dict) and charge.get("type") == "SUBSCRIPTION_FEE":
            return _money(charge.get("amount"))
    return _base_fee(data.tariff)


def _renew_date(item: dict) -> str | None:
    service = item.get("service")
    return service.get("renewDate") if isinstance(service, dict) else None


def _package_renewal(rests_detailed: list) -> datetime | None:
    """Earliest renewal among tariff packages (when the fee is charged).

    Prefers ``service.renewDate`` (the exact charge moment); ``endDay`` is
    23:59:59 of the day before, used only when ``renewDate`` is missing.
    """
    dates: list[datetime] = []
    for item in rests_detailed:
        if not isinstance(item, dict) or item.get("type") != "tariff":
            continue
        for raw in (_renew_date(item), item.get("endDay")):
            if not raw:
                continue
            try:
                dates.append(datetime.fromisoformat(raw))
                break
            except (ValueError, TypeError):
                continue
    return min(dates) if dates else None


def _tariff_packages(rests_detailed: list) -> list[dict]:
    return [
        {
            "uom": i.get("uom"),
            "remain": i.get("remain"),
            "endDay": i.get("endDay"),
            "renewDate": _renew_date(i),
        }
        for i in rests_detailed
        if isinstance(i, dict) and i.get("type") == "tariff"
    ]


@dataclass(frozen=True, kw_only=True)
class Tele2SensorDescription(SensorEntityDescription):
    """Describes a Tele2 sensor."""

    value_fn: Callable[[SubscriberData], Any]
    attrs_fn: Callable[[SubscriberData], dict] | None = None
    scope: Literal["all", "master"] = "all"  # "master" = master device only


SENSORS: tuple[Tele2SensorDescription, ...] = (
    Tele2SensorDescription(
        key="balance",
        translation_key="balance",
        native_unit_of_measurement="RUB",
        device_class=SensorDeviceClass.MONETARY,
        value_fn=lambda d: d.balance,
    ),
    Tele2SensorDescription(
        key="data_remaining",
        translation_key="data_remaining",
        native_unit_of_measurement="GB",
        value_fn=lambda d: d.rests.get("data"),
    ),
    Tele2SensorDescription(
        key="voice_remaining",
        translation_key="voice_remaining",
        native_unit_of_measurement="min",
        value_fn=lambda d: d.rests.get("voice"),
    ),
    Tele2SensorDescription(
        key="sms_remaining",
        translation_key="sms_remaining",
        value_fn=lambda d: d.rests.get("sms"),
    ),
    Tele2SensorDescription(
        key="rollover_data",
        translation_key="rollover_data",
        native_unit_of_measurement="GB",
        value_fn=lambda d: d.rollover.get("data"),
    ),
    Tele2SensorDescription(
        key="rollover_voice",
        translation_key="rollover_voice",
        native_unit_of_measurement="min",
        value_fn=lambda d: d.rollover.get("voice"),
    ),
    Tele2SensorDescription(
        key="rollover_sms",
        translation_key="rollover_sms",
        value_fn=lambda d: d.rollover.get("sms"),
    ),
    Tele2SensorDescription(
        key="sim_status",
        translation_key="sim_status",
        value_fn=lambda d: d.status or None,
    ),
    Tele2SensorDescription(
        key="tariff",
        translation_key="tariff",
        value_fn=lambda d: d.tariff.get("frontName") or d.tariff.get("tariffName"),
        attrs_fn=lambda d: {
            "abonent_fee": _money(
                d.tariff.get("currentAbonentFee") or d.tariff.get("abonentFee")
            )
        },
    ),
    Tele2SensorDescription(
        key="abonent_fee",
        translation_key="abonent_fee",
        native_unit_of_measurement="RUB",
        device_class=SensorDeviceClass.MONETARY,
        value_fn=_abonent_fee,
        attrs_fn=lambda d: {
            "base_fee": _base_fee(d.tariff),
            "period": d.tariff.get("period"),
        },
    ),
    Tele2SensorDescription(
        key="package_renewal",
        translation_key="package_renewal",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: _package_renewal(d.rests_detailed),
        attrs_fn=lambda d: {"packages": _tariff_packages(d.rests_detailed)},
    ),
    Tele2SensorDescription(
        key="linked_numbers",
        translation_key="linked_numbers",
        value_fn=lambda d: len(d.slaves),
        attrs_fn=lambda d: {
            "numbers": [s.get("msisdn") for s in d.slaves if isinstance(s, dict)],
            "details": d.slaves,
        },
        scope="master",
    ),
    Tele2SensorDescription(
        key="connected_services",
        translation_key="connected_services",
        scope="master",
        value_fn=lambda d: len(d.services),
        attrs_fn=lambda d: {
            "services": [
                {
                    "billing_id": s.get("billingId"),
                    "name": s.get("name"),
                    "fee": (s.get("abonentFee") or {}).get("amount")
                    if isinstance(s.get("abonentFee"), dict) else None,
                    "paid": bool((s.get("abonentFee") or {}).get("amount"))
                    and not s.get("free"),
                    "removable": bool(
                        (s.get("disconnectionAvailabilityStatus") or {}).get(
                            "canDisconnect"
                        )
                    ),
                    "status": s.get("status"),
                }
                for s in d.services if isinstance(s, dict)
            ],
            "monthly_fee": round(
                sum(
                    (s.get("abonentFee") or {}).get("amount", 0)
                    for s in d.services
                    if isinstance(s, dict) and isinstance(s.get("abonentFee"), dict)
                ),
                2,
            ),
            "paid_count": sum(
                1 for s in d.services
                if isinstance(s, dict)
                and (s.get("abonentFee") or {}).get("amount") and not s.get("free")
            ),
            "free_count": sum(
                1 for s in d.services
                if isinstance(s, dict)
                and not ((s.get("abonentFee") or {}).get("amount") and not s.get("free"))
            ),
        },
    ),
    Tele2SensorDescription(
        key="monthly_charges",
        translation_key="monthly_charges",
        native_unit_of_measurement="RUB",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _total_charges(d.charges),
        attrs_fn=lambda d: {
            "charges": d.charges,
            "by_category": _charges_by_category(d.charges),
        },
    ),
    Tele2SensorDescription(
        key="monthly_charges_subscription",
        translation_key="monthly_charges_subscription",
        native_unit_of_measurement="RUB",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _category_total(d.charges, CHARGE_SUBSCRIPTION),
        attrs_fn=lambda d: {"items": _category_items(d.charges, CHARGE_SUBSCRIPTION)},
    ),
    Tele2SensorDescription(
        key="monthly_charges_messages",
        translation_key="monthly_charges_messages",
        native_unit_of_measurement="RUB",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _category_total(d.charges, CHARGE_MESSAGES),
        attrs_fn=lambda d: {"items": _category_items(d.charges, CHARGE_MESSAGES)},
    ),
    Tele2SensorDescription(
        key="monthly_charges_content",
        translation_key="monthly_charges_content",
        native_unit_of_measurement="RUB",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _category_total(d.charges, CHARGE_CONTENT),
        attrs_fn=lambda d: {"items": _category_items(d.charges, CHARGE_CONTENT)},
    ),
    Tele2SensorDescription(
        key="monthly_charges_other",
        translation_key="monthly_charges_other",
        native_unit_of_measurement="RUB",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _other_total(d.charges),
        attrs_fn=lambda d: {"items": _other_items(d.charges)},
    ),
    Tele2SensorDescription(
        key="active_lots",
        translation_key="active_lots",
        value_fn=lambda d: len(d.lots),
        attrs_fn=lambda d: {"lots": d.lots},
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tele2 sensors — one device per discovered number."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime.coordinator
    data = coordinator.data
    entities: list[Tele2Sensor] = []
    for msisdn, sub in data.subscribers.items():
        for description in SENSORS:
            if description.scope == "master" and not sub.is_master:
                continue
            entities.append(Tele2Sensor(coordinator, description, msisdn, data.master))
    async_add_entities(entities)


class Tele2Sensor(CoordinatorEntity[Tele2Coordinator], SensorEntity):
    """A Tele2 sensor bound to a single subscriber number."""

    entity_description: Tele2SensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: Tele2Coordinator,
        description: Tele2SensorDescription,
        msisdn: str,
        master: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._msisdn = msisdn
        self._attr_unique_id = f"{msisdn}_{description.key}"
        info = DeviceInfo(
            identifiers={(DOMAIN, msisdn)},
            name=f"t2 {msisdn}",
            manufacturer="t2 (Tele2)",
        )
        if msisdn != master:
            info["via_device"] = (DOMAIN, master)
        self._attr_device_info = info

    @property
    def _subscriber(self) -> SubscriberData | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.subscribers.get(self._msisdn)

    @property
    def available(self) -> bool:
        return super().available and self._subscriber is not None

    @property
    def native_value(self) -> Any:
        sub = self._subscriber
        return None if sub is None else self.entity_description.value_fn(sub)

    @property
    def extra_state_attributes(self) -> dict | None:
        sub = self._subscriber
        if sub is None or self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(sub)
