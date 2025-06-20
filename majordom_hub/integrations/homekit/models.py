from typing import Any
from uuid import UUID

from aiohomekit.model.typed_dicts import PairingData
from schemas.device import Device, DeviceParameter, Parameter

# TODO: Codable or pydantic?

class HKParameterIntegrationData(Codable):
    type: UUID
    aid: int
    iid: int

class HKParameter(Parameter[HKParameterIntegrationData]): ...

class HKDeviceParameter(DeviceParameter[HKParameterIntegrationData]): ...

class HKDeviceIntegrationData(Codable): # freeform dict stored as json
    pairing_data: PairingData
    characteristics_cache: dict[str, Any] # TODO: resolve type anotation and check if needed

class HKDevice(Device[HKDeviceIntegrationData, HKParameter]): # TODO: generic with autoparse for HKDeviceData, or ask the delegate to return exactly HKDevice

    @property
    def hk_id(self) -> UUID:
        return self.integration_data.pairing_data["AccessoryPairingID"]
