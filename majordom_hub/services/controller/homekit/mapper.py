'''
Conversion logic between HAP (HomeKit Accessory Protocol) concepts and MajorDom's domain model.
Isolated here to keep the Controller free of boilerplate — formats, units, permissions, and valid enum values are all mapped in one place.
'''

import inspect
import re
from enum import Enum
from typing import Any, Iterable
from uuid import UUID, uuid5

from aiohomekit.model.characteristics import (
    Characteristic,
    CharacteristicFormats,
    CharacteristicUnits,
)
from aiohomekit.model.characteristics import const as aiohomekit_consts
from aiohomekit.model.characteristics.characteristic_types import CharacteristicsTypes
from aiohomekit.model.characteristics.permissions import CharacteristicPermissions
from aiohomekit.model.typed_dicts import HKDeviceID

from majordom_hub.schemas.parameter import (
    ParameterDataType,
    ParameterRole,
    ParameterState,
    ParameterUnit,
)
from majordom_hub.services.controller.homekit.models import (
    HKParameterIntegrationData,
    HKParameterState,
)


class HKMajorDomMapper:

    # MajorDom to HAP

    def mj_value_to_hap(self, value: Any):
        # TODO: implement conversion if needed
        # aiohomekit handle a lot of processing for us
        # use characteristic.format and characteristic.unit for correct conversion
        # checking existing mapping inside aiohomekit might be helpful
        return value

    # HAP to MajorDom

    def hap_char_to_majordom_parameter(self, device_id: UUID, aid: int, characteristic: Characteristic) -> ParameterState:
        return HKParameterState(
            id = uuid5(device_id, f'{aid}.{characteristic.iid}'),
            name = characteristic.description or '',
            data_type = self._hap_format_to_mj_data_type(characteristic.format),
            unit = self._hap_unit_to_mj(characteristic.unit),
            role = self._hap_perms_to_mj_role(characteristic.perms),
            min_value = characteristic.minValue,
            max_value = characteristic.maxValue or characteristic.maxLen,
            min_step = characteristic.minStep,
            valid_values = self._valid_values(characteristic),
            integration_data = HKParameterIntegrationData(
                type=characteristic.type,
                aid=aid,
                iid=characteristic.iid,
            )
        ).with_value(self.hap_value_to_mj(characteristic))
        # UNUSED:
            # Service.available
            # Characteristic.available
            # Characteristic.ev
            # Characteristic.maxDataLen
            # Characteristic.handle
            # Characteristic.broadcast_events
            # Characteristic.disconnected_events
            # Characteristic.valid_values_range

    def hap_id_to_uuid(self, hk_device_id: HKDeviceID) -> UUID:
        return uuid5(UUID(int=0), hk_device_id.lower())

    def hap_iid_to_param_uuid(self, hk_device_id: HKDeviceID, aid: int, iid: int) -> UUID:
        return uuid5(self.hap_id_to_uuid(hk_device_id), f'{aid}.{iid}')

    def hap_value_to_mj(self, characteristic: Characteristic):
        # characteristic.value should already work in most cases since aiohomekit handle a lot of processing for us
        # otherwise use characteristic.format and characteristic.unit for correct conversion
        # checking existing mapping inside aiohomekit might be helpful
        return characteristic.value

    def _hap_format_to_mj_data_type(self, format: CharacteristicFormats) -> ParameterDataType:
        return {
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
        }[format]

    def _hap_unit_to_mj(self, unit: CharacteristicUnits | None) -> ParameterUnit:
        return {
            CharacteristicUnits.celsius: ParameterUnit.celsius,
            CharacteristicUnits.percentage: ParameterUnit.percentage,
            CharacteristicUnits.arcdegrees: ParameterUnit.arcdegree,
            CharacteristicUnits.lux: ParameterUnit.lux,
            CharacteristicUnits.seconds: ParameterUnit.second,
            None: ParameterUnit.plain,
        }[unit]

    def _hap_perms_to_mj_role(self, perms: Iterable[CharacteristicPermissions]) -> ParameterRole:
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
            if char_type == characteristic.type:
                if values_enum := self._search_values_enum_by_name(char_type.name):
                    return values_enum

        # try using description as a type name
        if characteristic.description:
            possible_enum_name = '_'.join(characteristic.description.split(' ')).upper()
            if values_enum := self._search_values_enum_by_name(possible_enum_name):
                return values_enum

        return None

    def _search_values_enum_by_name(self, char_uppercase_name: str) -> type[Enum] | None:
        # ignore = {'values', 'target', 'current', 'state', 'status', 'capabilities', 'units'}
        searched_char_name_set = set(word.lower() for word in char_uppercase_name.split('_'))

        for name, obj in inspect.getmembers(aiohomekit_consts, inspect.isclass):
            if not issubclass(obj, Enum): continue
            member_name_set = set(word.lower() for word in re.split(r'(?<!^)(?=[A-Z])', name))
            # compare as sets because some enum names have different word order
            if searched_char_name_set == member_name_set:
               return obj
        return None

def underscore_to_display_case(name: str) -> str:
    return ' '.join([word.title() for word in name.split('_')])

# def from_underscore_case(name: str) -> list[str]:
#     return name.split('_')

# def from_display_case(name: str) -> list[str]:
#     return name.split(' ')

# def to_snake_case(words: list[str]) -> str:
#     return '_'.join(words).lower()

# def to_pascal_case(words: list[str]) -> str:
#     return ''.join([word.title() for word in words])

# def to_camel_case(words: list[str]) -> str:
#     return ''.join([words[0].lower()] + [word.title() for word in words[1:]])

# def to_upper_snake_case(words: list[str]) -> str:
#     return '_'.join(words).upper()
