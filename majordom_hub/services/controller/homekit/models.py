from typing import Any
from uuid import UUID

from aiohomekit.model.accessories import AccessoriesState
from aiohomekit.model.typed_dicts import PairingData
from pydantic import BaseModel, field_serializer, field_validator
from schemas.device import Device, DeviceState, ParameterState

from majordom_hub.schemas.base import Base
from majordom_hub.schemas.parameter import Parameter

# Integration data

class HKDeviceIntegrationData(Base):
    # NOTE: must be initializable without any arguments

    pairing_data: PairingData | None = None
    characteristics_cache: AccessoriesState | None = None

    # since AccessoriesState isn't a pydantic class, we need to implement (de)serialization

    class Config(Base.Config):
        arbitrary_types_allowed = True

    @field_serializer('characteristics_cache')
    def serialize_characteristics_cache(self, v: AccessoriesState, _info) -> dict[str, Any]:
        return v.as_dict() if v else {}

    @field_validator('characteristics_cache', mode='before')
    @classmethod
    def parse_characteristics_cache(cls, v: Any) -> AccessoriesState | None:
        if not v:
            return None
        if isinstance(v, AccessoriesState):
            return v
        if isinstance(v, dict):
            return AccessoriesState.from_dict(v)
        raise ValueError(f'Expected dict or AccessoriesState, got {type(v)}')

class HKParameterIntegrationData(BaseModel):
    type: UUID
    aid: int
    iid: int

# Overriding types for ease of use (shortcuts)

class HKParameter(Parameter):
    integration_data: HKParameterIntegrationData

class HKParameterState(ParameterState):
    integration_data: HKParameterIntegrationData

class HKDevice(Device):

    integration_data: HKDeviceIntegrationData

    @property
    def hk_id(self) -> str:
        assert self.integration_data and self.integration_data.pairing_data
        return self.integration_data.pairing_data["AccessoryPairingID"].lower()

# never used
class HKDeviceState(HKDevice, DeviceState):
    parameters: list[HKParameterState] # type: ignore # this class is only used in an isolated environment, and the type is used only for more convinient parsing, so the invariant exception can be ignored
