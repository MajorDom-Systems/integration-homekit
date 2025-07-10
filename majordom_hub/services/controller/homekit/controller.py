from typing import Any
from uuid import UUID

from aiohomekit.controller.abstract import (
    AbstractController,
    AbstractDiscovery,
    AbstractPairing,
)
from aiohomekit.controller.relay import Controller
from aiohomekit.model.characteristics.permissions import CharacteristicPermissions
from aiohomekit.model.typed_dicts import HKDeviceID, Response
from integrations.homekit.mapper import HKMajorDomMapper

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
from .models import HKDevice, HKParameter
from .pairings_storage import HKPairingsStorageMajorDom

# TODO: what are Accessory.needs_polling chars? handle them

class HomeKitController(MajorDomController):

    mapper: HKMajorDomMapper

    @property
    def name(self) -> str:
        return "HomeKit"

    # lifecycle

    async def start(self):
        self.mapper = HKMajorDomMapper()
        self.discoveries: dict[UUID, Discovery] = dict()
        self._pending_discoveries: dict[UUID, AbstractDiscovery] = dict()

        self.dependencies.register_zeroconf({
            "_hap._tcp.local.",
            "_hap._udp.local."
        })

        # TODO: Bluetooth discovery

        self._aiohomekit_controller = Controller(
            async_zeroconf_instance=self.dependencies.output.zeroconf_discovery.async_zeroconf,
            characteristics_storage=HKCharacteristicsStorageMajorDom(
                make_device_repository=self.dependencies.make_device_repository
            ),
            pairings_storage=HKPairingsStorageMajorDom(
                make_device_repository=self.dependencies.make_device_repository
            ),
        )
        self._aiohomekit_controller.on_discovery(self._aiohomekit_did_discover)
        await self._aiohomekit_controller.async_start()

    async def stop(self):
        await self._aiohomekit_controller.async_stop()

    async def pair_device(self, discovery: Discovery, credentials: CredentialsValue):
        discovery = self._pending_discoveries[discovery.id]
        finish_pairing = await discovery.async_start_pairing(discovery.id)
        # TODO: check if pairing steps need to be split
        pairing_data = await finish_pairing(credentials)
        pairing_id = pairing_data['AccessoryPairingID']
        # main "patch"/"create" data is saved in majordom's core
        # aiohomekit will save pairing data and characteristics (data model) automatically using the provided storage during finish_pairing
        # so no need to fetch or save anything manually here
        await self._handle_connected_pairing(pairing_id)
        self._pending_discoveries.pop(discovery.id)
        self.discoveries.pop(discovery.id)

    async def unpair(self, device: HKDevice):
        await self._aiohomekit_controller.remove_pairing(device.hk_id)
        # aiohomekit will cleanup the storage, so no need to do anything here

    async def identify(self, device: HKDevice):
        await self._aiohomekit_controller.identify(device.hk_id)

    async def send_command(self, command: DeviceCommand, device: HKDevice, parameter: HKParameter):
        majordom_value = command.value # TODO: convert

        pairing = self._aiohomekit_controller.pairings[device.hk_id]

        if not pairing:
            raise RuntimeError(f"Unexpected Error: Pairing {device.hk_id} for '{device.id}' aka '{device.name}' not found")

        response = await pairing.put_characteristics([parameter.integration_data.aid, parameter.integration_data.iid, majordom_value])
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
        for (aid, iid), response in responses.items():
            if response['status'] < 0:
                print(f"Something's wrong with characteristic {aid}.{iid}: ({response['status']}) {response['description']}")
        # TODO: handle results more properly

    # Observers

    async def _aiohomekit_did_discover(self, controller: AbstractController, discovery: AbstractDiscovery):

        # Discovered a paired device

        if discovery.id in controller.pairings:
            await self._handle_connected_pairing(discovery.id)
            return

        # Device is paired to some other controller

        if discovery.paired:
            # TODO: handle this case
            # If device supports only one controller, show as unreachable (requires unpairing)
            # Some protocols support multiple controllers (like Matter, some HomeKit, Zigbee green with hacks, etc.)
            # In this case, accessory might need to be put in pairing mode using the first controller to allow a second pairing with this controller
            print(f'Device "{discovery.description.name}" is paired to another controller')
            return

        # Discovered an unpaired device

        desc = discovery.description
        discovery_uuid = self.mapper.uuid_from_hk_id(discovery.id)
        discovery = Discovery(
            # technical
            id = discovery_uuid,
            controller = NonEmptyStr(self.name),
            credentials = CredentialsType.code.with_mask('DDD-DD-DDD'),
            expiration = None, # TODO:
            # UX
            transport = self.transport_type,
            device_name = desc.name,
            device_manufacturer = None, # looks like it needs device to be paired first
            device_category = desc.category,
            device_icon = None, # will be implemented later
            # device_model_id = None,
            # ? model_name: desc.model
        )
        self._pending_discoveries[discovery_uuid] = discovery
        self.discoveries[discovery_uuid] = discovery
        self.dependencies.output.controller_did_receive_discovery(self, discovery)

        # TODO: dismiss Discovery if discovery disapperd or expired

    def _aiohomekit_did_send_events(self, hk_device_id: str, events: dict[tuple[int, int], Any]):
        for (aid, iid), hk_value in events.items():
            device_id = self.mapper.uuid_from_hk_id(hk_device_id)
            device_parameter_id = self.mapper.param_uuid_from_hk(device_id, aid, iid)
            majordom_event = DeviceParameterChangedEvent(
                device_id=device_id,
                parameter_id=device_parameter_id,
                value=hk_value, # TODO: convert
            )
            self.dependencies.output.controller_did_receive_device_event(self, majordom_event)
