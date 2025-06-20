from aiohomekit.model.accessories import AccessoriesState
from aiohomekit.model.typed_dicts import HKDeviceID
from providers import DeviceProvider

from .mapper import HKMajorDomMapper
from .models import HKDevice, HKDeviceIntegrationData


class HKCharacteristicsStorageMajorDom:

    device_provider: DeviceProvider

    def __init__(self, device_provider: DeviceProvider):
        self.device_provider = device_provider
        self.mapper = HKMajorDomMapper()

    # CharacteristicsStorageProtocol Implementation

    async def get_all(self) -> dict[HKDeviceID, AccessoriesState]:
        all = {}
        for device in await self.device_provider.get_all():
            if (accessory := device.integration_data.characteristics):
                all[device.hk_id] = accessory
        return all

    async def get(self, id: HKDeviceID) -> AccessoriesState | None:
        # TODO: make sure model is up to date when MajorDom changes some data directly without this integration
        uuid = self.mapper.uuid_from_hk_id(id)
        if (
            (device := await self.device_provider.get(uuid)) and \
            (accessory := device.integration_data.characteristics) \
        ):
            return accessory
        return None

    async def save(self, id: HKDeviceID, item: AccessoriesState):
        # NOTE: this method is called only when data model (characteristics) is updated
        # which is detected by a change of config_num
        # usually after the accessory's software update

        device_id = self.mapper.uuid_from_hk_id(id)
        device = await self.device_provider.get(device_id, as_=HKDevice) # should already be created by the core # TODO: implement .get(as_=)
        if not device.integration_data:
            device.integration_data = HKDeviceIntegrationData()

        # fill only the unique data from AccessoryState that isn't already passed from PendingPairing or DeviceCreate by the core
        # TODO: check these values with real devices

        accessory = item.accessories[0] # TODO: add later support for multiple accessories
        device.manufacturer = accessory.manufacturer
        device.integration_data.characteristics_cache = item

        # map all homekit characteristics to majordom parameters
        # TODO: get rid of the deprecated device_model in the core

        for accessory in item.accessories:
            for service in accessory.services:
                for characteristic in service.characteristics:
                    parameter = self.mapper.majordom_parameter_from_characteristic(device, accessory.aid, characteristic)
                    device.parameters.append(parameter)

        await self.device_provider.save(device)

    async def delete(self, id: HKDeviceID) -> None:
        # TODO: check usage, remove vs unpair
        uuid = self.mapper.uuid_from_hk_id(id)
        if device := await self.device_provider.get(uuid, as_=HKDevice):
            device.integration_data.characteristics_cache = None # TODO: empty collection?
            await self.device_provider.save(device)
