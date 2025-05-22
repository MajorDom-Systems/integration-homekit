class HAPPairingsStorageMajorDom:
    ...
    # easy, just store data

    device_provider: DeviceProvider

    def __init__(self, device_provider: DeviceProvider):
        self.device_provider = device_provider

    # aiohomekit.PairingsStorageType

    async def get_model(self, hap_pairing_id: str) -> Pairing | None: # TODO: which pairing? check data load in the controller
        if ( # TODO: provuder.get(as=)? experiment with python generics
            (device := await self.device_provider.get(hap_pairing_id)) and \
            (hap_device := HapDevice(device)) and \
            (pairing_data := hap_device.integration_data.pairing_data)
        ):
            return Pairing(self._aiohomekit_controller, pairing_data)
        return None

    async def delete_model(self, hap_pairing_id: str):
        # TODO: check usage
        if (
            (device := await self.device_provider.get(hap_pairing_id)) and \
            hap_device := HapDevice(device)
        ):
            device.integration_data.pairing_data = None # TODO: empty collection?
            await self.device_provider.save(hap_device)
