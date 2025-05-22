from typing import Any, Callable, Iterable
from uuid import uuid5
from functools import wraps

import aiohomekit
from aiohomekit.controller.abstract import AbstractController, AbstractDiscovery
from aiohomekit.model.characteristics import Characteristic
from aiohomekit.model.characteristics.permissions import CharacteristicPermissions
from aiohomekit.model import Accessories

from framework.abstract_integration import AbstractIntegration

from providers import DeviceProvider

from .models import (
    HAPDevice,
    HAPParameter,
)
from .pairings_storage import HAPPairingsStorageMajorDom
from .characteristics_storage import HAPCharacteristicsStorageMajorDom


# NOTES: aiohomekit duplicates all data cached in memory. Perhaps making it stateless and using a separated controllable storage is better (at least for ram).
class HomeKitIntegration(AbstractIntegration):

    @property
    def _device_provider(self) -> DeviceProvider:
        return self.delegate.device_provider

    # lifecycle

    async def on_delegate_init(self): # aka start
        self.register_zeroconf({
            "_hap._tcp.local.",
            "_hap._udp.local."
        }) # TODO: check if it handles all subdomains e.g. YLBulbColor1s-98A3._hap._tcp.local
        # TODO: check zeroconf data model and fine-tune discovery by wildcard and by name
        # TODO: Blt and thread

        self._aiohomekit_controller = await self._get_aiohomekit_controller()

    async def stop(self):
        await self._aiohomekit_controller.async_stop()

    async def aiohomekit_controller_did_discover(self, controller: AbstractController, discovery: AbstractDiscovery):
        if not discovery.paired:
            desc = discovery.description

            print(f"\nName: {desc.name}")
            print(f"Device ID (id): {desc.id}")
            if hasattr(desc, "model"):
                print(f"Model Name (md): {desc.model}")
            if hasattr(desc, "feature_flags"):
                print(f"Feature Flags (ff): {desc.feature_flags!s}")
            if desc.status_flags:
                print(f"Status Flags (sf): {desc.status_flags!s}")
            print(f"Category (ci): {desc.category!s}")
            print(f"Transport: {transport_type}")
            if hasattr(desc, "address"):
                print(f"Address: {desc.address}")
            if hasattr(desc, "port"):
                print(f"Port: {desc.port}")

            self.delegate.add_pending_pairing(DevicePairing(desc.id, discovery, credentials = CredentialsType.code.with_mask('DDD-DD-DDD'), expiration = None))
            return

        # Paired branch

        pairing = controller.pairings.get(discovery.id)

        if not pairing:
            print(f"unexpecetd: Pairing not found for {discovery.id}")
            return

        state = await pairing.fetch_accessories_and_characteristics()

        if device := await self._device_provider.get(discovery.id, as=HAPDevice):
            # char_map and pairings_data are already saved using the storage provided to the controller under the aiohomekit's hood
            # but they need to be parsed and mapped to majordom device model
            await self._subscribe_device(pairing)
            self.delegate.notify_connected_device(device)
        else:
            print('Failed to get device from discovery')

    async def pair_device(self, discovery: aiohomekit.AbstractDiscovery, code: str):
        # TODO: check if split is needed
        finish_pairing = await discovery.async_start_pairing(discovery.id)
        pairing = await finish_pairing(code)
        # await self.identify(pairing.id)
        # TODO: save new device? in char_storage?

    async def unpair(self, id):
        await self._aiohomekit_controller.remove_pairing(id)
        # TODO: handle else

    async def identify(self, id: str):
        await self._aiohomekit_controller.identify(id)
        # if pairing := self._aiohomekit_controller.pairings.get(id):
        #     await pairing.identify()
        # TODO: handle else

    # async def fetch(self, id: str) -> DeviceState: # TODO: check if needed. Also, split into fetching entire data model and quickly fetching only the state

    async def send_command(self, action: Action):
        majordom_device_id = action.device_id
        majordom_parameter_id = action.parameter_id
        majordom_value = action.value # TODO: convert

        hap_device = await self._device_provider.get(majordom_device_id, as=HomeKitDevice)

        if not hap_device:
            raise UnexpectedException(f"Device {majordom_device_id} not found")

        hap_parameter = hap_device.get_parameter(majordom_parameter_id)

        if not hap_parameter:
            raise UnexpectedException(f"Parameter {majordom_parameter_id} not found in device {majordom_device_id}")

        pairing = self._aiohomekit_controller.pairings.get(majordom_device_id):

        if not pairing:
            raise UnexpectedException(f"Pairing {majordom_device_id} not found")

        results = await pairing.put_characteristics([hap_parameter.integration_data.aid, hap_parameter.integration_data.iid, majordom_value])

    # Private

    def _on_device_event(self, device_id: str, events: dict[tuple[int,int], Any]):
        for (aid, iid), hap_value in events:
            device_parameter_id = uuid5(device_id, f'{aid}.{iid}') # TODO: Parameter.id vs DeviceParameter.id, see the db
            action = Action(
                device_id=device_id,
                parameter_id=device_parameter_id,
                value=hap_value, # TODO: convert
            )
            self.delegate.device_did_send_event(majordom_event)

    # Helpers

    async def _fetch_device(self, host, pairings) -> something: # TODO: implement
        # fetch the schema and the state
        # map to majordom device model
        # map each parameter
        # return device
        return ...

    # def _generate_device_id(self, device_discovery) -> str: # TODO: Integration protocol?
    #     # TODO: unique, constant, unchangeable; mac addr - ok; ip - not ok; serial - ok
    #     ...

    # def _map_to_majordom_parameter(self, dict) -> Parameter:
    #     # Generic mapping magic here
    #     ...

    # AioHomekit Wrappers

    async def _get_aiohomekit_controller(self) -> aiohomekit.Controller:
        # TODO: standartize pairings and charmap file names, injection, and implementation
        controller = Controller(
            async_zeroconf_instance=self.delegate.zeroconf_discovery.zeroconf,
            characteristics_storage=HAPCharacteristicsStorageMajorDom(), # TODO: custom CharacteristicCache that stores in device.integration_data
            pairings_storage=HAPPairingsStorageMajorDom(
                device_provider=self._device_provider
            ), # TODO: custom PairingsStorage that stores in device.integration_data
        )
        # TODO: fork and implement PairingsStorage that stores in device.integration_data using the example of char_cache
        controller.load_data() # TODO: call on controller.async_start insteads
        await controller.async_start() # TODO: check if blocking
        controller.on_discovery(self.aiohomekit_controller_did_discover)
        return controller

    async def _subscribe_device(self, pairing: Pairing):
        characteristics_ids: list[tuple[int, int]] = []

        for accessory in pairing._accessories_state.accessories:
            for service in accessory.services:
                for characteristic in service.characteristics:
                    if CharacteristicPermissions.events in characteristic.perms:
                        characteristics_ids.append((accessory.aid, characteristic.iid))

        pairing.dispatcher_connect(self._on_device_event)
        results = await pairing.subscribe(characteristics_ids)

        for (aid, iid), value in results.items():
            if value['status'] < 0:
                print(f"Error subscribing to {aid}.{iid}: ({value['status']}) {value['description']}")
