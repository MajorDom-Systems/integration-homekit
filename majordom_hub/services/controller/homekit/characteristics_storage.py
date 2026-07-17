"""
HomeKit-specific storage adapter.
TLDR;
aiohomekit manages pairing and characteristics data internally, but delegates persistence to a pluggable storage interface.
This class implements that interface on top of MajorDom's DeviceRepository, so HomeKit state is stored in the Hub's database.
"""

from typing import AsyncContextManager, Callable

from aiohomekit.model.accessories import AccessoriesState
from aiohomekit.model.typed_dicts import HKDeviceID
from aiohomekit.storage.characteristics_storage import CharacteristicsStorageProtocol

from majordom_hub.repository.device_repository import DeviceRepository

from .mapper import HKMajorDomMapper
from .models import HKDevice, HKDeviceIntegrationData, HKDeviceState


class HKCharacteristicsStorageMajorDom(CharacteristicsStorageProtocol):
    def __init__(
        self,
        make_device_repository: Callable[[], AsyncContextManager[DeviceRepository]],
        mapper: HKMajorDomMapper,
    ):
        self.make_device_repository = make_device_repository
        self.mapper = mapper

    @property
    def _integration_name(self):
        return "HomeKit"

    # CharacteristicsStorageProtocol Implementation

    async def get_all(self) -> dict[HKDeviceID, AccessoriesState]:
        all = {}
        async with self.make_device_repository() as device_repository:
            for device in await device_repository.get_all(as_=HKDevice):
                if accessory := device.integration_data.characteristics_cache:
                    all[device.hk_id] = accessory
        return all

    async def get(self, id: HKDeviceID) -> AccessoriesState | None:
        uuid = self.mapper.hap_id_to_uuid(id)
        async with self.make_device_repository() as device_repository:
            if (device := await device_repository.get(uuid, as_=HKDevice)) and (accessory := device.integration_data.characteristics_cache):
                return accessory
        return None

    async def save(self, id: HKDeviceID, item: AccessoriesState):
        # NOTE: this method is called only when data model (characteristics) is updated
        # which is detected by a change of config_num
        # usually after the accessory's software update
        async with self.make_device_repository() as device_repository:
            device_id = self.mapper.hap_id_to_uuid(id)
            device = await device_repository.state(device_id, as_=HKDeviceState)
            assert device
            if not device.integration_data:
                device.integration_data = HKDeviceIntegrationData()

            # fill only the unique data from AccessoryState that isn't already passed from Discovery or DeviceCreate by the core
            # TODO: check these values with real devices

            accessory = item.accessories[0]  # TODO: add later support for multiple accessories
            device.manufacturer = accessory.manufacturer
            device.integration_data.characteristics_cache = item

            # map all homekit characteristics to majordom parameters

            for accessory in item.accessories:
                for service in accessory.services:
                    for characteristic in service.characteristics:
                        parameter = self.mapper.hap_char_to_majordom_parameter(device.id, accessory.aid, characteristic)
                        device.parameters.append(parameter)

            await device_repository.save(device)

    async def delete(self, id: HKDeviceID):
        # TODO: check usage, remove vs unpair, allow fast re-pairing
        async with self.make_device_repository() as device_repository:
            uuid = self.mapper.hap_id_to_uuid(id)
            if device := await device_repository.get(uuid, as_=HKDevice):
                device.integration_data.characteristics_cache = None  # TODO: empty collection?
                await device_repository.save(device)
