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
from schemas.device import PendingPairing

from integrations.framework.abstract_integration import (
    AbstractIntegration,
    CredentialsType,
)
from integrations.homekit.mapper import HKMajorDomMapper
from majordom_hub.schemas.device import CredentialsValue
from majordom_hub.schemas.merlin import DeviceAction

from .characteristics_storage import HKCharacteristicsStorageMajorDom
from .models import HKDevice
from .pairings_storage import HKPairingsStorageMajorDom


class HomeKitIntegration(AbstractIntegration):

    mapper: HKMajorDomMapper
    _pending_discoveries: dict[UUID, AbstractDiscovery]

    @property
    def name(self):
        return "HomeKit"

    # lifecycle

    async def start(self):
        self.mapper = HKMajorDomMapper()
        self._pending_discoveries = {}

        self.register_zeroconf({
            "_hap._tcp.local.",
            "_hap._udp.local."
        })

        # TODO: Bluetooth discovery

        self._aiohomekit_controller = Controller(
            async_zeroconf_instance=self.delegate.zeroconf_discovery.async_zeroconf,
            characteristics_storage=HKCharacteristicsStorageMajorDom(
                device_provider=self.device_provider
            ),
            pairings_storage=HKPairingsStorageMajorDom(
                device_provider=self.device_provider
            ),
        )
        self._aiohomekit_controller.on_discovery(self.aiohomekit_controller_did_discover)
        await self._aiohomekit_controller.async_start()

    async def stop(self):
        await self._aiohomekit_controller.async_stop()

    async def aiohomekit_controller_did_discover(self, controller: AbstractController, discovery: AbstractDiscovery):

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
        self._pending_discoveries[discovery_uuid] = discovery

        self.delegate.add_pending_pairing(
            PendingPairing(
                # technical
                id = discovery_uuid,
                integration = self.name,
                credentials = CredentialsType.code.with_mask('DDD-DD-DDD'),
                expiration = None, # TODO:
                # UX
                transport = controller.transport_type,
                device_name = desc.name,
                device_manufacturer = None, # TODO:
                device_category = desc.category,
                device_icon = None, # TODO:
                device_model_id = None,
                # ? model_name: desc.model
            )
        )

        # TODO: dismiss PendingPairing if discovery disapperd or expired

    async def pair_device(self, pending_id: UUID, credentials: CredentialsValue):
        discovery = self._pending_discoveries[pending_id]
        finish_pairing = await discovery.async_start_pairing(discovery.id)
        # TODO: check if pairing steps need to be split
        pairing_data = await finish_pairing(credentials)
        pairing_id = pairing_data['AccessoryPairingID']
        # aiohomekit will save pairing data and characteristics (data model) automatically using the provided storage during finish_pairing
        # so no need to fetch or save anything manually here
        # main "patch" data is saved in majordom's core
        # TODO: save data from discovery that is not accessible from accessory; TODO: pass it to pairing inside aiohomekit?
        await self._handle_connected_pairing(pairing_id)

    async def unpair(self, id: UUID):
        device = await self.device_provider.get(id, as_=HKDevice)
        await self._aiohomekit_controller.remove_pairing(device.hk_id)
        # aiohomekit will cleanup the storage

    async def identify(self, id: UUID):
        device = await self.device_provider.get(id, as_=HKDevice)
        await self._aiohomekit_controller.identify(device.hk_id)

    async def send_command(self, action: DeviceAction): # TODO: Command vs Action vs Event
        majordom_device_id = action.device_id
        majordom_parameter_id = action.parameter_id
        majordom_value = action.value # TODO: convert

        hk_device = await self.device_provider.get(majordom_device_id, as_=HKDevice)

        if not hk_device:
            raise RuntimeError(f"Unexpected Error: Device {majordom_device_id} not found")

        hk_parameter = hk_device.get_parameter(majordom_parameter_id)

        if not hk_parameter:
            raise RuntimeError(f"Unexpected Error: Parameter {majordom_parameter_id} not found in device {majordom_device_id}")

        pairing = self._aiohomekit_controller.pairings[majordom_device_id]

        if not pairing:
            raise RuntimeError(f"Unexpected Error: Pairing {majordom_device_id} not found")

        response = await pairing.put_characteristics([hk_parameter.integration_data.aid, hk_parameter.integration_data.iid, majordom_value])
        self._handle_accessory_response(response)

    # Private

    def _hk_device_did_send_events(self, hk_device_id: str, events: dict[tuple[int, int], Any]):
        for (aid, iid), hk_value in events.items():
            device_id = self.mapper.uuid_from_hk_id(hk_device_id)
            device_parameter_id = self.mapper.param_uuid_from_hk(device_id, aid, iid) # TODO: Parameter.id vs DeviceParameter.id, see the db
            majordom_event = DeviceAction( # TODO: action vs event
                device_id=device_id,
                parameter_id=device_parameter_id,
                value=hk_value, # TODO: convert
            )
            self.delegate.device_did_send_event(majordom_event)

    async def _handle_connected_pairing(self, pairing_id: HKDeviceID):
        await self._observe_characteristics(self._aiohomekit_controller.pairings[pairing_id])
        # TODO: check whether _observe_characteristics gets the current state; call and process `get_characteristics` if it doesn't
        device = await self.device_provider.get(self.mapper.uuid_from_hk_id(pairing_id))
        self.delegate.notify_connected_device(device)

    async def _observe_characteristics(self, pairing: AbstractPairing):
        characteristics_ids: list[tuple[int, int]] = []

        for accessory in pairing._accessories_state.accessories:
            for service in accessory.services:
                for characteristic in service.characteristics:
                    if CharacteristicPermissions.events in characteristic.perms:
                        characteristics_ids.append((accessory.aid, characteristic.iid))

        cleanup = pairing.add_observer_for_characteristics(self._hk_device_did_send_events)
        self._aiohomekit_controller._pairing_cleanups[pairing.id].append(cleanup) # make controller handle cleanup for us
        # pairing.add_observer_for_availability # TODO: check and use

        response = await pairing.subscribe_characteristics(characteristics_ids)
        self._handle_accessory_response(response)

    def _handle_accessory_response(self, response: Response):
        for (aid, iid), value in response.items():
            if value['status'] < 0:
                print(f"Something's wrong with characteristic {aid}.{iid}: ({value['status']}) {value['description']}")
        # TODO: handle results more properly
