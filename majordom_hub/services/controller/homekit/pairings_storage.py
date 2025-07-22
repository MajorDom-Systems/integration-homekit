from typing import AsyncContextManager, Callable

from aiohomekit.model.typed_dicts import HKDeviceID, PairingData
from aiohomekit.storage.pairing_data_storage import PairingDataStorageProtocol

from majordom_hub.repository.device_repository import DeviceRepository

from .mapper import HKMajorDomMapper
from .models import HKDevice


class HKPairingsStorageMajorDom(PairingDataStorageProtocol):

    def __init__(self, make_device_repository: Callable[[], AsyncContextManager[DeviceRepository]]):
        self.make_device_repository = make_device_repository
        self.mapper = HKMajorDomMapper()

    @property
    def _integration_name(self):
        return "HomeKit"

    # aiohomekit.PairingsStorageType

    async def get_all(self) -> dict[HKDeviceID, PairingData]:
        all = {}
        async with self.make_device_repository() as device_repository:
            for device in await device_repository.get_all(integration=self._integration_name, as_=HKDevice):
                if (pairing_data := device.integration_data.pairing_data):
                    all[device.id] = pairing_data
        return all

    async def get(self, id: str) -> PairingData | None:
        uuid = self.mapper.hap_id_to_uuid(id)
        async with self.make_device_repository() as device_repository:
            if (
                (device := await device_repository.get(uuid, as_=HKDevice)) and \
                (pairing_data := device.integration_data.pairing_data)
            ):
                return pairing_data
        return None

    async def save(self, id: str, item: PairingData):
        uuid = self.mapper.hap_id_to_uuid(id)
        async with self.make_device_repository() as device_repository:
            if ((device := await device_repository.get(uuid))):
                device.integration_data.pairing_data = item
                await device_repository.save(device)

    async def delete_model(self, id: str):
        # TODO: check usage
        uuid = self.mapper.hap_id_to_uuid(id)
        async with self.make_device_repository() as device_repository:
            if ((device := await device_repository.get(uuid))):
                device.integration_data.pairing_data = None
                await device_repository.save(device)
                # TODO: check if should delete the device
                # Discussion:
                    # this class is responsible solely for managing pairing data storage, and should not be used for any other purpose.
                    # However, we should ensure there is no case of aiohomekit disconnecting from the device without notifying us.
