import asyncio
from typing import Any, Iterable
from uuid import UUID

from aiohomekit.controller.abstract import (
    AbstractController,
    AbstractDiscovery,
    AbstractPairing,
)
from aiohomekit.controller.relay import Controller as AioHomeKitController
from aiohomekit.controller.relay import controller as controller_module
from aiohomekit.model.characteristics.permissions import CharacteristicPermissions
from aiohomekit.model.typed_dicts import HKDeviceID, Response

from majordom_hub.schemas.automation.events import DeviceParameterChangedEvent
from majordom_hub.schemas.base import NonEmptyStr
from majordom_hub.schemas.command import DeviceCommand
from majordom_hub.schemas.device import (
    CredentialsType,
    CredentialsValue,
    Discovery,
)
from majordom_hub.services.controller.framework.abstract_controller import (
    AbstractController as MajorDomController,  # avoid collision with aiohomekit
)

from .characteristics_storage import HKCharacteristicsStorageMajorDom
from .mapper import HKMajorDomMapper
from .models import HKDevice, HKParameter
from .pairings_storage import HKPairingsStorageMajorDom

# TODO: make a better way to pass this
controller_module.BLE_TRANSPORT_SUPPORTED = False
controller_module.COAP_TRANSPORT_SUPPORTED = False
controller_module.IP_TRANSPORT_SUPPORTED = True

# TODO: what are Accessory.needs_polling chars? handle them

class HomeKitController(MajorDomController):

    mapper: HKMajorDomMapper

    @property
    def name(self) -> str:
        return "HomeKit"

    @property
    def discoveries(self) -> dict[UUID, Discovery]:
        return self._majordom_discoveries

    # lifecycle

    async def start(self):
        self.mapper = HKMajorDomMapper()
        self._majordom_discoveries: dict[UUID, Discovery] = dict()
        self._hap_discoveries: dict[UUID, AbstractDiscovery] = dict()

        self.dependencies.register_zeroconf({ # TODO: delegate
            "_hap._tcp.local.",
            "_hap._udp.local."
        })

        # TODO: Bluetooth discovery

        self._aiohomekit_controller = AioHomeKitController(
            zeroconf_instance=self.dependencies.zeroconf,
            char_cache=HKCharacteristicsStorageMajorDom(
                make_device_repository=self.dependencies.make_device_repository
            ),
            pairing_data_storage=HKPairingsStorageMajorDom(
                make_device_repository=self.dependencies.make_device_repository
            ),
        )
        self._aiohomekit_controller.on_discovery(self._aiohomekit_did_discover)
        await self._aiohomekit_controller.start()

    async def stop(self):
        await self._aiohomekit_controller.stop()

    async def pair_device(self, discovery: Discovery, credentials: CredentialsValue | None):
        hap_discovery = self._hap_discoveries[discovery.id]
        print(f'Pairing: {hap_discovery.description.name} at {hap_discovery.description.address}:{hap_discovery.description.port}')
        async with asyncio.timeout(3): # TODO: timeout to settings
            finish_pairing = await hap_discovery.start_pairing()
        # TODO: check if pairing steps need to be split
        async with asyncio.timeout(3):
            pairing_data = await finish_pairing(str(credentials or ''))
        pairing_id = pairing_data['AccessoryPairingID']
        # main "patch"/"create" data is saved in majordom's core
        # aiohomekit will save pairing data and characteristics (data model) automatically using the provided storage during finish_pairing
        # so no need to fetch or save anything manually here
        await self._handle_connected_pairing(pairing_id)
        self._hap_discoveries.pop(discovery.id)
        self._majordom_discoveries.pop(discovery.id)

    async def unpair(self, device: HKDevice):
        await self._aiohomekit_controller.remove_pairing(device.hk_id)
        # aiohomekit will cleanup the storage, so no need to do anything here

    async def identify(self, device: HKDevice):
        await self._aiohomekit_controller.identify(device.hk_id)

    async def fetch(self, device: HKDevice):
        pairing = self._aiohomekit_controller.pairings[device.hk_id]
        if not pairing:
            raise RuntimeError(f"Unexpected Error: Pairing {device.hk_id} for '{device.id}' aka '{device.name}' not found")

        # fetching the values only; aiohomekit will save the data model on change automatically
        response = await pairing.get_characteristics([device.hk_id])
        self._aiohomekit_did_send_events(device.hk_id, response)

    async def send_command(self, command: DeviceCommand, device: HKDevice, parameter: HKParameter):
        hk_value = self.mapper.mj_value_to_hap(command.value)

        pairing = self._aiohomekit_controller.pairings[device.hk_id]

        if not pairing:
            raise RuntimeError(f"Unexpected Error: Pairing {device.hk_id} for '{device.id}' aka '{device.name}' not found")

        response = await pairing.put_characteristics([parameter.integration_data.aid, parameter.integration_data.iid, hk_value])
        self._handle_accessory_response(response)

    # Private

    # Helpers

    async def _handle_connected_pairing(self, pairing_id: HKDeviceID):
        pairing = self._aiohomekit_controller.pairings[pairing_id]
        await self._observe_characteristics(pairing)
        state = await pairing.get_characteristics(pairing)
        self._aiohomekit_did_send_events(pairing_id, state)
        self.dependencies.output.controller_did_connect_device(self, self.mapper.uuid_from_hk_id(pairing_id))

    async def _observe_characteristics(self, pairing: AbstractPairing):
        characteristics_ids: list[tuple[int, int]] = []

        for accessory in pairing._accessories_state.accessories:
            for service in accessory.services:
                for characteristic in service.characteristics:
                    if CharacteristicPermissions.events in characteristic.perms:
                        characteristics_ids.append((accessory.aid, characteristic.iid))

        cleanup = pairing.add_observer_for_characteristics(self._aiohomekit_did_send_events)
        self._aiohomekit_controller._pairing_cleanups[pairing.id].append(cleanup) # make controller handle cleanup for us
        # pairing.add_observer_for_availability # TODO: check and use

        response = await pairing.subscribe_characteristics(characteristics_ids)
        self._handle_accessory_response(response)

    def _handle_accessory_response(self, responses: Response):
        # TODO: handle results more properly
        for (aid, iid), response in responses.items():
            if response['status'] != 0: # TODO: test
                raise ValueError(f"Something's wrong with characteristic {aid}.{iid}: ({response['status']}) {response['description']}")

    # Observers

    def _aiohomekit_did_discover(self, controller: AbstractController, hk_discovery: AbstractDiscovery):
        asyncio.create_task(self._async_aiohomekit_did_discover(controller, hk_discovery))

    async def _async_aiohomekit_did_discover(self, controller: AbstractController, hk_discovery: AbstractDiscovery):

        # Discovered a paired device

        if hk_discovery.description.id in controller.pairings:
            print(f'{self.name} Discovered paired device...')
            await self._handle_connected_pairing(hk_discovery.description.id)
            return

        # Discovery is paired to some other controller

        if hk_discovery.paired:
            # TODO: handle this case
            # If device supports only one controller, show as unreachable (requires unpairing)
            # Some protocols support multiple controllers (like Matter, some HomeKit, Zigbee green with hacks, etc.)
            # In this case, accessory might need to be put in pairing mode using the first controller to allow a second pairing with this controller
            print(f'Device "{hk_discovery.description.name}" is paired to another controller')
            return

        # Discovered an unpaired device
        print(f'{self.name} Discovered new device...')
        desc = hk_discovery.description
        discovery_uuid = self.mapper.hap_id_to_uuid(hk_discovery.description.id)
        mj_discovery_info = Discovery(
            # technical
            id = discovery_uuid,
            integration = NonEmptyStr(self.name),
            credentials = CredentialsType.code.with_mask('DDD-DD-DDD'),
            expiration = None, # TODO:
            # UX
            transport = NonEmptyStr('ip'),
            device_name = desc.name,
            device_manufacturer = None, # looks like it needs device to be paired first
            device_category = desc.category,
            device_icon = None, # will be implemented later
            # device_model_id = None,
            # ? model_name: desc.model
        )
        self._hap_discoveries[discovery_uuid] = hk_discovery
        self._majordom_discoveries[discovery_uuid] = mj_discovery_info
        self.dependencies.output.controller_did_receive_discovery(self, mj_discovery_info)

        # TODO: dismiss Discovery if discovery disapperd or expired

    def _aiohomekit_did_send_events(self, hk_device_id: str, events: dict[tuple[int, int], Any]):
        self.dependencies.output.controller_did_receive_device_events(self, self._aiohomekit_events_to_majordom(hk_device_id, events))

    def _aiohomekit_events_to_majordom(self, hk_device_id: str, events: dict[tuple[int, int], Any]) -> Iterable[DeviceParameterChangedEvent]:
        for (aid, iid), hk_value in events.items():
            device_id = self.mapper.hap_id_to_uuid(hk_device_id)
            device_parameter_id = self.mapper.hap_iid_to_param_uuid(hk_device_id, aid, iid)
            yield DeviceParameterChangedEvent(
                device_id=device_id,
                parameter_id=device_parameter_id,
                value=self.mapper.hap_value_to_mj(hk_value)
            )
