from typing import AsyncContextManager, Callable

from aiohomekit.controller.abstract.pairing import AbstractPairing
from aiohomekit.controller.zeroconf.ip.pairing import IpPairing

from majordom_hub.repository.device_repository import DeviceRepository

from .mapper import HKMajorDomMapper
from .models import HKDevice


class HKPairingsStorageMajorDom:
    ...
    # easy, just store data

    make_device_repository: Callable[[], AsyncContextManager[DeviceRepository]]

    def __init__(self, make_device_repository: Callable[[], AsyncContextManager[DeviceRepository]]):
        self.make_device_repository = make_device_repository
        self.mapper = HKMajorDomMapper()

    # aiohomekit.PairingsStorageType

    async def get_model(self, hk_pairing_id: str) -> AbstractPairing | None:
        uuid = self.mapper.uuid_from_hk_id(hk_pairing_id)
        async with self.make_device_repository() as device_repository:
            if (
                (device := await device_repository.get(uuid, as_=HKDevice)) and \
                (pairing_data := device.integration_data.pairing_data)
            ):
                return IpPairing(pairing_data) # TODO: switch and handle all transports
        return None

    async def delete_model(self, hk_pairing_id: str):
        # TODO: check usage
        uuid = self.mapper.uuid_from_hk_id(hk_pairing_id)
        async with self.make_device_repository() as device_repository:
            if ((device := await device_repository.get(uuid))):
                device.integration_data.pairing_data = None
                await device_repository.save(device)
                # TODO: check if should delete the device
                # Discussion:
                    # this class is responsible solely for managing pairing data storage, and should not be used for any other purpose.
                    # However, we should ensure there is no case of aiohomekit disconnecting from the device without notifying us.
