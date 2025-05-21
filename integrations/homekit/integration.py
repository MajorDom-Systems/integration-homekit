# NOTES: aiohomekit duplicates all data cached in memory. Perhaps making it stateless and using a separated controllable storage is better (at least for ram).


from typing import Iterable

from aiohomekit.controller.abstract import AbstractController, AbstractDiscovery
from framework.abstract_integration import AbstractIntegration


class HAPDeviceData(Codable): # freeform dict stored as json
    pairings: PairingData
    characteristics: dict[str, Any] # TODO: resolve

class HAPDevice(Device[HAPDeviceData]): # TODO: generic with autoparse for HAPDeviceData, or ask the delegate to return exactly HAPDevice
    ...

class HomeKitIntegration(AbstractIntegration):

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

        # NOTE: full zeroconf service type may be unique and available all the time in discovery e.g. YLBulbColor1s-98A3._hap._tcp.local has unique id "YLBulbColor1s-98A3"

        # TODO: difference between models: discovery, pending pairing, pairing, connected device

        # Parigin statuses:
            # 1. pending pairing - offer user to pair
                # 1.2 pairing in progress?
            # 2. unpaired but not pending - possible? not sure. if yes, ignore (now) or show user as detected but unavailable, reason: "not in pairing mode"
            # 3. paired to someone else, not connected - ignore (now) or show user as detected but unavailable, reason: "paired to someone else"
            # 4. paired to us, not connected - identify, update addr, notify connected, subscribe to events if needed
            # 5. paired to us, connected - shouldn't be called in discovery. process like 3 but don't duplicate data

        # Unpaired branch

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
            print(f"Configuration number (c#): {desc.config_num}")
            print(f"State Number (s#): {desc.state_num}")
            print(f"Paired: {discovery.paired}")
            print(f"Transport: {transport_type}")
            if hasattr(desc, "address"):
                print(f"Address: {desc.address}")
            if hasattr(desc, "port"):
                print(f"Port: {desc.port}")
            print('')

            self.delegate.add_pending_pairing(DevicePairing(desc.id, discovery, credentials = CredentialsType.code.with_mask('DDD-DD-DDD'), expiration = None))
            return

        # Paired branch

        pairing = controller.pairings.get(discovery.id)

        if not pairing:
            print(f"unexpecetd: Pairing not found for {discovery.id}")
            return

        state = await pairing.fetch_accessories_and_characteristics()

        if device := await self.try_get_device(discovery.id, as=HomeKitDevice):
            # char_map and pairings_data are already saved using the storage provided to the controller under the aiohomekit's hood
            # TODO: observe device status
            self.delegate.notify_connected_device(device)
        else:
            print('Failed to get device from discovery')

    async def pair_device(self, discovery: aiohomekit.AbstractDiscovery, code: str):
        # TODO: check if split is needed
        finish_pairing = await discovery.async_start_pairing(discovery.id)
        pairing = await finish_pairing(code)

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
        majordom_value = action.value
        # device_id -> pairing_data -> addr + credentials
        # majordom_parameter_id -> device-native attribute
        # convert majordom_value to device-native value
        # send
        #
        # TODO: check Characteristic.validate_value impl, def check_convert_value

    # Private

    def _on_device_event(self, device_id: str, data: dict[tuple[int,int], Any]):

        for (aid, iid), hap_value in data:
            # device_id.aid.iid -> majordom_device_parameter
            # hap_value -> majordom_value
            ...

        majordom_event = <convert hap_event> # TOOD:
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
            pairings_storage=HAPPairingsStorageMajorDom(), # TODO: custom PairingsStorage that stores in device.integration_data
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

class HAPCharacteristicStorageMajorDom(aiohomekit.CharacteristicsStorageMemory):
    ...

class HAPPairingsStorageMajorDom(aiohomekit.PairingsStorageMemory):
    ...
