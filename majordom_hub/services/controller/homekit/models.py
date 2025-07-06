from uuid import UUID

from aiohomekit.model.accessories import AccessoriesState
from aiohomekit.model.typed_dicts import PairingData
from pydantic import BaseModel
from schemas.device import Device, Parameter, ParameterState

# Integration data

class HKParameterIntegrationData(BaseModel):
    type: UUID
    aid: int
    iid: int

class HKDeviceIntegrationData(BaseModel):
    pairing_data: PairingData | None = None
    characteristics_cache: AccessoriesState | None = None

# Overriding types for ease of use (shortcuts)

class HKParameter(Parameter):
    integration_data: HKParameterIntegrationData

class HKParameterState(ParameterState):
    integration_data: HKParameterIntegrationData

class HKDevice(Device):

    integration_data: HKDeviceIntegrationData | None = None

    @property
    def hk_id(self) -> str:
        assert self.integration_data and self.integration_data.pairing_data
        return self.integration_data.pairing_data["AccessoryPairingID"]

# never used
# class HKDeviceState(HKDevice, DeviceState):
#     parameters: list[HKParameterState] # type: ignore # this class is only used in an isolated environment, and the type is used only for more convinient parsing, so the invariant exception can be ignored
