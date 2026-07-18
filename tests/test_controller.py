"""Unit tests driving HomeKitController directly (no Hub).

Each asserts on both sides: what the controller reported back via the recording output, and
what actually happened on the virtual accessory / in the repository.
"""

import asyncio
from uuid import UUID as _UUID

import pytest
from aiohomekit.controller.zeroconf.ip import IpPairing
from aiohomekit.model.characteristics import CharacteristicKey
from conftest import BRIGHTNESS_PARAM_ID, DEVICE_ID, ON_PARAM_ID, provisional_device
from majordom_integration_sdk.schemas.command import DeviceCommand
from majordom_integration_sdk.schemas.device import CredentialsType, ProvidedCredentials

from majordom_homekit.models import HKDevice, HKParameter, HKParameterIntegrationData

UUID_ONE = _UUID(int=1)


async def _wait_for(predicate, timeout: float = 2.0):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.02)


async def test_discovers_unpaired_accessory(unpaired_server, controller, dependencies):
    await unpaired_server()
    output = dependencies.output

    await _wait_for(lambda: bool(output.received_discoveries))

    assert DEVICE_ID in controller.discoveries
    discovery = controller.discoveries[DEVICE_ID]
    assert discovery.integration == "HomeKit"
    assert discovery.transport == "IP"
    assert discovery.device_name == "Testlicht"
    assert CredentialsType.code in discovery.expected_credentials_options
    assert output.received_discoveries[-1].id == DEVICE_ID


async def test_pairs_a_discovered_device(unpaired_server, controller, dependencies, repository):
    server = await unpaired_server()
    output = dependencies.output
    await _wait_for(lambda: DEVICE_ID in controller.discoveries)

    # the Hub has already created the device row before calling pair_device
    async with repository.session() as repo:
        await repo.save(provisional_device())

    discovery = controller.discoveries[DEVICE_ID]
    await controller.pair_device(discovery, ProvidedCredentials(type=CredentialsType.code, value="031-45-154"))

    # device side: the accessory is now paired
    assert server.data.is_paired
    # Hub side: the controller reported the connect, and dropped the discovery
    assert DEVICE_ID in output.connected_devices
    assert DEVICE_ID not in controller.discoveries
    # persistence: pairing data landed in the device's integration_data
    async with repository.session() as repo:
        device = await repo.get(DEVICE_ID, as_=HKDevice)
    assert device is not None
    assert device.integration_data.pairing_data
    assert device.integration_data.pairing_data["AccessoryPairingID"] == "12:34:56:00:01:0A"


async def test_pair_device_rejects_wrong_credentials_type(unpaired_server, controller):
    await unpaired_server()
    await _wait_for(lambda: DEVICE_ID in controller.discoveries)
    discovery = controller.discoveries[DEVICE_ID]
    with pytest.raises(ValueError):
        await controller.pair_device(discovery, ProvidedCredentials(type=CredentialsType.qr, value="x"))


from majordom_homekit.models import HKDeviceIntegrationData


def _brightness_parameter() -> HKParameter:
    return HKParameter(
        id=BRIGHTNESS_PARAM_ID,
        name="Brightness",
        data_type="integer",
        unit="plain",
        role="control",
        visibility="user",
        integration_data=HKParameterIntegrationData(type=UUID_ONE, aid=1, iid=10),
    )


def _hk_device(pairing_data) -> HKDevice:
    return HKDevice(
        id=DEVICE_ID,
        name="Testlicht",
        room_id=UUID_ONE,
        transport="IP",
        integration="HomeKit",
        manufacturer="lusiardi.de",
        integration_data=HKDeviceIntegrationData(pairing_data=pairing_data, characteristics_cache=None),
    )


async def test_unpairs_a_device(paired_server, controller, dependencies):
    server, pairing_data = paired_server
    await _wait_for(lambda: DEVICE_ID in dependencies.output.connected_devices)
    assert server.data.is_paired

    await controller.unpair(_hk_device(pairing_data))
    assert not server.data.is_paired


async def test_sends_a_command_to_the_device(paired_server, controller, dependencies):
    _, pairing_data = paired_server
    await _wait_for(lambda: DEVICE_ID in dependencies.output.connected_devices)

    value = 42
    brightness = _brightness_parameter()

    await controller.send_command(
        DeviceCommand(device_id=DEVICE_ID, parameter_id=BRIGHTNESS_PARAM_ID, value=value),
        _hk_device(pairing_data),
        brightness,
    )
    # device side: the accessory actually took the new brightness
    got = await IpPairing(pairing_data).get_characteristics([CharacteristicKey(1, 10)])
    assert got == {CharacteristicKey(1, 10): {"value": value}}


async def test_reports_device_state_as_events_on_connect(paired_server, controller, dependencies):
    # The device -> Hub reporting path: on connecting to a paired accessory the controller
    # reads its characteristics and reports each as a DeviceParameterChange. (This is what the
    # Hub's e2e test_events actually exercises — it uses value == the initial, so it never
    # distinguished a pushed change; the mock accessory server doesn't deliver async pushes
    # to the observer in-process. The reporting *channel* is what matters and is covered here.)
    _, pairing_data = paired_server
    output = dependencies.output
    await _wait_for(lambda: DEVICE_ID in output.connected_devices)

    await _wait_for(lambda: any(e.parameter_id == ON_PARAM_ID for e in output.events))
    on_events = [e for e in output.events if e.parameter_id == ON_PARAM_ID]
    assert on_events[-1].value is False  # the accessory's ON characteristic starts False


async def test_identify(paired_server, controller, dependencies):
    _, pairing_data = paired_server
    await _wait_for(lambda: DEVICE_ID in dependencies.output.connected_devices)
    # smoke: identify reaches the accessory without error
    await controller.identify(_hk_device(pairing_data))
