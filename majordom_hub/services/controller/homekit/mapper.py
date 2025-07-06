import inspect
import re
from enum import Enum
from uuid import UUID, uuid5

from aiohomekit.model.characteristics import Characteristic
from aiohomekit.model.characteristics import const as aiohomekit_consts
from aiohomekit.model.characteristics.characteristic_types import CharacteristicsTypes
from aiohomekit.model.characteristics.permissions import CharacteristicPermissions
from aiohomekit.model.typed_dicts import HKDeviceID
from schemas.device import ParameterRole, ParameterState
from typimg import Iterable

from .models import HKParameterIntegrationData, HKParameterState


class HKMajorDomMapper:

    # HomeKit to MajorDom

    def uuid_from_hk_id(self, hk_device_id: HKDeviceID) -> UUID:
        return uuid5(UUID(int=0), hk_device_id)

    def param_uuid_from_hk(self, hk_device_id: HKDeviceID, aid: int, iid: int) -> UUID:
        return uuid5(self.uuid_from_hk_id(hk_device_id), f'{aid}.{iid}')

    def majordom_parameter_from_characteristic(self, device_id: UUID, aid: int, characteristic: Characteristic) -> ParameterState:
        # return HKParameter(
        return HKParameterState(
            id=self.param_uuid_from_hk(device_id, aid, characteristic.iid),
            name = characteristic.description,
            data_type = characteristic.format, # TODO: convert
            unit = characteristic.unit, # TODO: convert
            role = self._role_from_perms(characteristic.perms),
            min_value = characteristic.minValue,
            max_value = characteristic.maxValue or characteristic.maxLen,
            min_step = characteristic.minStep,
            valid_values = self._valid_values(characteristic),
            integration_data = HKParameterIntegrationData(
                type=characteristic.type,
                aid=aid,
                iid=characteristic.iid,
            ),
            value = characteristic.value # TODO: convert
            # UNUSED:
                # Service.available
                # Characteristic.available
                # Characteristic.ev
                # Characteristic.maxDataLen
                # Characteristic.handle
                # Characteristic.broadcast_events
                # Characteristic.disconnected_events
                # Characteristic.valid_values_range
        )

    def _role_from_perms(self, perms: Iterable[CharacteristicPermissions]) -> ParameterRole:
        # TODO: review all perms in specs
        if CharacteristicPermissions.paired_write in perms:
            return ParameterRole.control
        elif CharacteristicPermissions.paired_read in perms:
            return ParameterRole.sensor
        else:
            return ParameterRole.event

    def _valid_values(self, characteristic: Characteristic) -> dict[int, str] | None:
        # TODO: convert to codegen instead of runtime parsing
        if values_enum := self._search_values_enum_for_characteristic(characteristic):
            return {v.value: underscore_to_display_case(k) for k, v in values_enum.__members__.items()}
        else:
            return {key: str(key) for key in characteristic.validValues}

    def _search_values_enum_for_characteristic(self, characteristic: Characteristic) -> type[Enum] | None:

        # try get characteristic type name by id
        for char_type in CharacteristicsTypes:
            if char_type.id == characteristic.type:
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
            if searched_char_name_set == member_name_set:
               return obj

# def from_underscore_case(name: str) -> list[str]:
#     return name.split('_')

# def from_display_case(name: str) -> list[str]:
#     return name.split(' ')

def underscore_to_display_case(name: str) -> str:
    return ' '.join([word.title() for word in name.split('_')])

# def to_snake_case(words: list[str]) -> str:
#     return '_'.join(words).lower()

# def to_pascal_case(words: list[str]) -> str:
#     return ''.join([word.title() for word in words])

# def to_camel_case(words: list[str]) -> str:
#     return ''.join([words[0].lower()] + [word.title() for word in words[1:]])

# def to_upper_snake_case(words: list[str]) -> str:
#     return '_'.join(words).upper()
