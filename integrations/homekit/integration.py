


class HomeKitIntegration(AbstractIntegration):

    # lifecycle

    async def on_delegate_init(self):
        self.register_zeroconf(type="_hap._tcp.local.") # use abstract class
        # TODO: check zeroconf data model and fine-tune discovery by wildcard and by name
        # TODO: Blt and thread

    async def on_discovery(self, discovery_info: Iterable[DeviceDiscovery]):
        # TODO: difference between discovery, pending pairing, pairing, connected device
        for discovery in discovery_info:
            id = self.get_device_id_from_discovery(discovery) # mac or hash or something constant, not network address (dhcp can change the ip, device can use different port); UPD: can require fetching, use temp id here instead and hash-based after pairing

            if not id:
                print('Unexpected behavior: can\'t generate device id from discovery')
                continue

            if device := self.try_get_device(id): # TODO: str alias system to find device in db by discovery or fetch info, NOT IP (ip is not not reliable since can change on dhcp)
                # check if can be moved to framework or to abstract class
                self.delegate.add_connected_device(device)

            self.delegate.add_pending_pairing(DevicePairing(id, discovery, credentials = Credentials.code.with_mask('DDD-DD-DDD'))) # TODO: allow ignore # FUTURE

    async def on_start_pairing(self, id, pairing, credentials) -> Pairing:
        # TODO
        pass

    async def on_finish_pairing(self, id: str?, pairing?, credentials: Credentials) -> ConnectedDevice?:
        # TODO
        return

    async def unpair(self, id): ... # TODO

    async def fetch(self, id: str) -> DeviceState:
        # get device data from the db
        # self._fetch_device(...)
        ...

    async def send_command(self, action: Action):
        majordom_device_id = action.device_id
        majordom_parameter_id = action.parameter_id
        majordom_value = action.value
        # device_id -> pairing_data -> addr + credentials
        # majordom_parameter_id -> device-native attribute
        # convert majordom_value to device-native value
        # send

    # Private

    def _on_device_event(self, hap_event: HapEvent):
        majordom_event = <convert hap_event> # TOOD:
        delegate.device_did_send_event(majordom_event)

    # Helpers

    async def _fetch_device(self, host, pairings) -> something:
        # fetch the schema and the state
        # map to majordom device model
        # map each parameter
        # return device
        return ...

    def _generate_device_id(self, device_discovery) -> str: # TODO: Integration protocol?
        # TODO: unique, constant, unchangeable; mac addr - ok; ip - not ok; serial - ok
        ...

    # def _map_to_majordom_parameter(self, dict) -> Parameter:
    #     # Generic mapping magic here
    #     ...
