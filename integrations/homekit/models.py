from typing import Any
from uuid import UUID
from schemas.device import Device, Parameter, DeviceParameter


class HAPParameterIntegrationData(Codable):
    type: UUID
    aid: int
    iid: int

class HAPParameter(Parameter[HAPParameterIntegrationData]): ...

class HAPDeviceParameter(DeviceParameter[HAPParameterIntegrationData]): ...

class HAPDeviceIntegrationData(Codable): # freeform dict stored as json
    pairing_data: PairingData
    characteristics_cache: dict[str, Any] # TODO: resolve type anotation and check if needed

class HAPDevice(Device[HAPDeviceIntegrationData, HAPParameter]): # TODO: generic with autoparse for HAPDeviceData, or ask the delegate to return exactly HAPDevice
    ...
