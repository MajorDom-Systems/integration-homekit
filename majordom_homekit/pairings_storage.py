"""
TLDR: same purpose as characteristics_storage.py
"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from aiohomekit.model.typed_dicts import HKDeviceID, PairingData
from aiohomekit.storage.pairing_data_storage import PairingDataStorageProtocol
from majordom_integration_sdk.repository import DeviceRepositoryProtocol

from .mapper import HKMajorDomMapper
from .models import HKDevice


class HKPairingsStorageMajorDom(PairingDataStorageProtocol):
    def __init__(
        self,
        make_device_repository: Callable[[], AbstractAsyncContextManager[DeviceRepositoryProtocol]],
        mapper: HKMajorDomMapper,
    ):
        self.make_device_repository = make_device_repository
        self.mapper = mapper

    @property
    def _integration_name(self):
        return "HomeKit"

    # aiohomekit.PairingsStorageType

    async def get_all(self) -> dict[HKDeviceID, PairingData]:
        # keyed by the HAP pairing id (HKDeviceID), matching HKCharacteristicsStorage.get_all
        # and what aiohomekit looks pairings up by — not the MajorDom device UUID.
        pairings: dict[HKDeviceID, PairingData] = {}
        async with self.make_device_repository() as device_repository:
            for device in await device_repository.get_all(as_=HKDevice):
                if pairing_data := device.integration_data.pairing_data:
                    pairings[device.hk_id] = pairing_data
        return pairings

    async def get(self, id: str) -> PairingData | None:
        uuid = self.mapper.hap_id_to_uuid(id)
        async with self.make_device_repository() as device_repository:
            if (device := await device_repository.get(uuid, as_=HKDevice)) and (
                pairing_data := device.integration_data.pairing_data
            ):
                return pairing_data
        return None

    async def save(self, id: str, item: PairingData):
        uuid = self.mapper.hap_id_to_uuid(id)
        async with self.make_device_repository() as device_repository:
            if device := await device_repository.get(uuid, as_=HKDevice):
                device.integration_data.pairing_data = item
                await device_repository.save(device)

    async def delete_model(self, id: str):
        # TODO: check usage
        uuid = self.mapper.hap_id_to_uuid(id)
        async with self.make_device_repository() as device_repository:
            if device := await device_repository.get(uuid):
                device.integration_data.pairing_data = None
                await device_repository.save(device)
                # TODO: check if should delete the device
                # Discussion:
                # this class is responsible solely for managing pairing data storage, and should
                # not be used for any other purpose.
                # However, we should ensure there is no case of aiohomekit disconnecting from the
                # device without notifying us.
