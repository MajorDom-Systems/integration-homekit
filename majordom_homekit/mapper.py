"""
Conversion logic between HAP (HomeKit Accessory Protocol) concepts and MajorDom's domain model.
Isolated here to keep the Controller free of boilerplate — formats, units, permissions, and valid
enum values are all mapped in one place.
"""

import inspect
import re
from collections.abc import Callable, Iterable
from enum import Enum
from typing import Any
from uuid import UUID

from aiohomekit.model.characteristics import (
    Characteristic,
    CharacteristicFormats,
    CharacteristicUnits,
)
from aiohomekit.model.characteristics import const as aiohomekit_consts
from aiohomekit.model.characteristics.characteristic_types import CharacteristicsTypes
from aiohomekit.model.characteristics.permissions import CharacteristicPermissions
from aiohomekit.model.typed_dicts import HKDeviceID
from majordom_integration_sdk.schemas.parameter import (
    ParameterDataType,
    ParameterRole,
    ParameterUnit,
    ParameterVisibility,
)

from majordom_homekit.models import (
    HKParameterIntegrationData,
    HKParameterState,
)


class HKMajorDomMapper:
    def __init__(
        self,
        device_uuid: Callable[[str], UUID],
        parameter_uuid: Callable[[UUID, str], UUID],
    ):
        # The controller's provided (framework) UUID generators — see AbstractController.
        # HAP identifiers are turned into MajorDom UUIDs exclusively through these, so device
        # and parameter ids are namespaced under the integration consistently with every other
        # integration.
        self._device_uuid = device_uuid
        self._parameter_uuid = parameter_uuid

    # -------------------------------------------------------------------------
    # Identity: HAP identifiers -> MajorDom UUIDs
    # -------------------------------------------------------------------------

    def hap_id_to_uuid(self, hk_device_id: HKDeviceID) -> UUID:
        return self._device_uuid(hk_device_id.lower())

    def hap_iid_to_param_uuid(self, hk_device_id: HKDeviceID, aid: int, iid: int) -> UUID:
        return self._parameter_uuid(self.hap_id_to_uuid(hk_device_id), f"{aid}.{iid}")

    # -------------------------------------------------------------------------
    # MajorDom -> HAP
    # -------------------------------------------------------------------------

    def mj_value_to_hap(self, value: Any):
        # TODO: implement conversion if needed
        # aiohomekit handle a lot of processing for us
        # use characteristic.format and characteristic.unit for correct conversion
        # checking existing mapping inside aiohomekit might be helpful
        return value

    # -------------------------------------------------------------------------
    # HAP -> MajorDom
    # -------------------------------------------------------------------------

    def hap_char_to_majordom_parameter(
        self, device_id: UUID, aid: int, characteristic: Characteristic
    ) -> HKParameterState:
        return HKParameterState(
            id=self._parameter_uuid(device_id, f"{aid}.{characteristic.iid}"),
            name=characteristic.description or "",
            data_type=self._hap_format_to_mj_data_type(characteristic.format),
            unit=self._hap_unit_to_mj(characteristic.unit),
            role=self._hap_perms_to_mj_role(characteristic.perms),
            visibility=ParameterVisibility.user,
            min_value=characteristic.minValue,
            max_value=characteristic.maxValue or characteristic.maxLen,
            min_step=characteristic.minStep,
            valid_values=self._valid_values(characteristic),
            integration_data=HKParameterIntegrationData(
                type=characteristic.type,
                aid=aid,
                iid=characteristic.iid,
            ),
            value=self.hap_value_to_mj(characteristic),
        )
        # UNUSED:
        # Service.available
        # Characteristic.available
        # Characteristic.ev
        # Characteristic.maxDataLen
        # Characteristic.handle
        # Characteristic.broadcast_events
        # Characteristic.disconnected_events
        # Characteristic.valid_values_range

    def hap_value_to_mj(self, characteristic: Characteristic):
        # characteristic.value should already work in most cases since aiohomekit handle a lot of processing for us
        # otherwise use characteristic.format and characteristic.unit for correct conversion
        # checking existing mapping inside aiohomekit might be helpful
        return characteristic.value

    def _hap_format_to_mj_data_type(self, format: str | None) -> ParameterDataType:
        mapping: dict[str | None, ParameterDataType] = {
            CharacteristicFormats.bool: ParameterDataType.bool,
            CharacteristicFormats.uint8: ParameterDataType.integer,
            CharacteristicFormats.uint16: ParameterDataType.integer,
            CharacteristicFormats.uint32: ParameterDataType.integer,
            CharacteristicFormats.uint64: ParameterDataType.integer,
            CharacteristicFormats.int: ParameterDataType.integer,
            CharacteristicFormats.int32: ParameterDataType.integer,
            CharacteristicFormats.float: ParameterDataType.decimal,
            CharacteristicFormats.string: ParameterDataType.string,
            CharacteristicFormats.data: ParameterDataType.data,
            # TODO: review
            CharacteristicFormats.tlv8: ParameterDataType.data,
            CharacteristicFormats.array: ParameterDataType.data,
            CharacteristicFormats.dict: ParameterDataType.data,
        }
        return mapping[format]

    def _hap_unit_to_mj(self, unit: str | None) -> ParameterUnit:
        mapping: dict[str | None, ParameterUnit] = {
            CharacteristicUnits.celsius: ParameterUnit.celsius,
            CharacteristicUnits.percentage: ParameterUnit.percentage,
            CharacteristicUnits.arcdegrees: ParameterUnit.arcdegree,
            CharacteristicUnits.lux: ParameterUnit.lux,
            CharacteristicUnits.seconds: ParameterUnit.second,
            None: ParameterUnit.plain,
        }
        return mapping[unit]

    def _hap_perms_to_mj_role(self, perms: Iterable[str]) -> ParameterRole:
        # TODO: review all perms in specs
        if CharacteristicPermissions.paired_write in perms:
            return ParameterRole.control
        elif CharacteristicPermissions.paired_read in perms:
            return ParameterRole.sensor
        else:
            return ParameterRole.event

    def _valid_values(self, characteristic: Characteristic) -> dict[int | str | float, str] | None:
        # TODO: convert to codegen instead of runtime parsing
        if values_enum := self._search_values_enum_for_characteristic(characteristic):
            return {v.value: underscore_to_display_case(k) for k, v in values_enum.__members__.items()}
        else:
            return {key: str(key) for key in characteristic.valid_values or []}

    # scrapping

    def _search_values_enum_for_characteristic(self, characteristic: Characteristic) -> type[Enum] | None:
        # try get characteristic type name by id
        for char_type in CharacteristicsTypes:
            if char_type == characteristic.type and (values_enum := self._search_values_enum_by_name(char_type.name)):
                return values_enum

        # try using description as a type name
        if characteristic.description:
            possible_enum_name = "_".join(characteristic.description.split(" ")).upper()
            if values_enum := self._search_values_enum_by_name(possible_enum_name):
                return values_enum

        return None

    def _search_values_enum_by_name(self, char_uppercase_name: str) -> type[Enum] | None:
        # ignore = {'values', 'target', 'current', 'state', 'status', 'capabilities', 'units'}
        searched_char_name_set = set(word.lower() for word in char_uppercase_name.split("_"))

        for name, obj in inspect.getmembers(aiohomekit_consts, inspect.isclass):
            if not issubclass(obj, Enum):
                continue
            member_name_set = set(word.lower() for word in re.split(r"(?<!^)(?=[A-Z])", name))
            # compare as sets because some enum names have different word order
            if searched_char_name_set == member_name_set:
                return obj


def underscore_to_display_case(name: str) -> str:
    return " ".join([word.title() for word in name.split("_")])
