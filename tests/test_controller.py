"""Unit tests driving HomeKitController directly (no Hub).

Each asserts on both sides: what the controller reported back via the recording output, and
what actually happened on the virtual accessory / in the repository.
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID as _UUID

import pytest
from aiohomekit.controller.zeroconf.ip import IpPairing
from aiohomekit.exceptions import AccessoryDisconnectedError
from aiohomekit.model.characteristics import CharacteristicKey
from aiohomekit.model.transport_type import TransportType
from aiohomekit.testing.mock_zeroconf import AsyncServiceBrowserStub, DNSCache, MockedAsyncServiceInfo
from aiohomekit.testing.utils import next_available_port
from conftest import (
    BRIGHTNESS_PARAM_ID,
    DEVICE_ID,
    HAP_TYPE_TCP,
    HK_ID,
    ON_PARAM_ID,
    PAIRING_DATA,
    needs_aiohomekit_lifetime_fixes,
    provisional_device,
)
from majordom_integration_sdk import Peripherals
from majordom_integration_sdk.schemas.command import DeviceCommand
from majordom_integration_sdk.schemas.device import CredentialsType, ProvidedCredentials
from majordom_integration_sdk.testing import FakeZeroconf

from majordom_homekit import HomeKitController
from majordom_homekit.models import HKDevice, HKDeviceState, HKParameter, HKParameterIntegrationData

UUID_ONE = _UUID(int=1)
CONNECT_TIMEOUT = "aiohomekit.controller.zeroconf.ip.pairing.asyncio_timeout"  # its 10 s wait for an accessory


async def _wait_for(predicate, timeout: float = 2.0):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.02)


def _reconnect_loops() -> list[asyncio.Task[Any]]:
    return [task for task in asyncio.all_tasks() if "_reconnect" in repr(task.get_coro())]


async def _cut_off(server, pairing):
    """The accessory's HAP server is gone (unplugged, hung), its mDNS records are not."""
    await _wait_for(lambda: pairing.is_connected)
    server.shutdown()
    server.server_close()
    pairing.connection.transport.close()
    await _wait_for(lambda: not pairing.is_connected)


def test_has_no_discoveries_before_it_starts(platform):
    # The runtime starts it only once its zeroconf runs; the Hub may list discoveries before.
    assert HomeKitController(platform).discoveries == {}


async def test_stops_after_a_start_that_failed_early(platform):
    # The runtime stops it after any failed start; here its zeroconf was never bound
    controller = HomeKitController(platform)
    with pytest.raises(KeyError, match="mdns"):
        await controller.start()
    await controller.stop()


async def test_refuses_a_zeroconf_that_isnt_running(platform):
    controller = HomeKitController(platform)
    controller.peripherals = Peripherals({"mdns": FakeZeroconf().endpoint})  # holds no AsyncZeroconf
    with patch("aiohomekit.controller.relay.controller.AsyncZeroconf") as own:  # what aiohomekit opens instead
        own.return_value.zeroconf.cache = DNSCache()
        own.return_value.zeroconf.listeners = [AsyncServiceBrowserStub()]
        own.return_value.async_close = AsyncMock()
        with pytest.raises(RuntimeError, match="zeroconf"):
            await controller.start()
        await controller.stop()
    assert not own.called


async def test_restarts_on_the_same_instance(paired_server, controller, output, repository):
    # what the runtime does on a restart, a retry or zeroconf coming back
    await _wait_for(lambda: DEVICE_ID in output.connected_devices)
    before = controller._aiohomekit.pairings[HK_ID]
    await controller.stop()
    output.connected_devices.clear()

    await controller.start()
    await _wait_for(lambda: DEVICE_ID in output.connected_devices)
    assert controller._aiohomekit.pairings[HK_ID] is not before
    async with repository() as repo:
        device = await repo.state(DEVICE_ID, as_=HKDeviceState)
    assert device is not None
    ids = [p.id for p in device.parameters]
    assert len(ids) == len(set(ids))


@needs_aiohomekit_lifetime_fixes
async def test_stop_closes_the_accessory_sessions(paired_server, controller, output):
    await _wait_for(lambda: DEVICE_ID in output.connected_devices)
    pairing = controller._aiohomekit.pairings[HK_ID]
    await _wait_for(lambda: pairing.is_connected)

    await controller.stop()
    assert not pairing.is_connected  # each restart would open one more of the accessory's few sessions


@needs_aiohomekit_lifetime_fixes
async def test_starts_with_a_paired_accessory_offline(platform, zeroconf, output, repository):
    async with repository() as repo:
        await repo.save(provisional_device({**PAIRING_DATA, "AccessoryPort": next_available_port()}))  # none there
    controller = HomeKitController(platform)
    controller.output = output
    controller.peripherals = Peripherals({"mdns": zeroconf.endpoint})

    async with asyncio.timeout(2):  # its reachability is the device's state, not the start's
        await controller.start()
    await controller.stop()
    assert DEVICE_ID not in output.connected_devices


async def test_discovers_unpaired_accessory(unpaired_server, controller, output):
    await unpaired_server()

    await _wait_for(lambda: bool(output.received_discoveries))

    assert DEVICE_ID in controller.discoveries
    discovery = controller.discoveries[DEVICE_ID]
    assert discovery.integration == "homekit"
    assert discovery.transport == "IP"
    assert discovery.device_name == "Testlicht"
    assert CredentialsType.code in discovery.expected_credentials_options
    assert output.received_discoveries[-1].id == DEVICE_ID


async def test_pairs_a_discovered_device(unpaired_server, controller, output, repository):
    server = await unpaired_server()
    await _wait_for(lambda: DEVICE_ID in controller.discoveries)

    # the Hub has already created the device row before calling pair_device
    async with repository() as repo:
        await repo.save(provisional_device())

    discovery = controller.discoveries[DEVICE_ID]
    await controller.pair_device(discovery, ProvidedCredentials(type=CredentialsType.code, value="031-45-154"))

    # device side: the accessory is now paired
    assert server.data.is_paired
    # Hub side: the controller reported the connect, and dropped the discovery
    assert DEVICE_ID in output.connected_devices
    assert DEVICE_ID not in controller.discoveries
    # persistence: pairing data landed in the device's integration_data
    async with repository() as repo:
        device = await repo.get(DEVICE_ID, as_=HKDevice)
    assert device is not None
    assert device.integration_data.pairing_data
    assert device.integration_data.pairing_data["AccessoryPairingID"] == "12:34:56:00:01:0A"


async def test_pairs_an_accessory_slower_than_a_second(unpaired_server, controller, repository):
    server = await unpaired_server()
    await _wait_for(lambda: DEVICE_ID in controller.discoveries)
    async with repository() as repo:
        await repo.save(provisional_device())
    hap_discovery = controller._hap_discoveries[DEVICE_ID]
    start_pairing = hap_discovery.start_pairing

    async def slow_start_pairing():  # SRP takes seconds on a slow accessory MCU
        await asyncio.sleep(1.2)
        return await start_pairing()

    with patch.object(hap_discovery, "start_pairing", slow_start_pairing):
        discovery = controller.discoveries[DEVICE_ID]
        await controller.pair_device(discovery, ProvidedCredentials(type=CredentialsType.code, value="031-45-154"))
    assert server.data.is_paired


async def test_keeps_a_pairing_whose_first_read_fails(unpaired_server, controller, repository, caplog):
    server = await unpaired_server()
    await _wait_for(lambda: DEVICE_ID in controller.discoveries)
    async with repository() as repo:
        await repo.save(provisional_device())

    discovery = controller.discoveries[DEVICE_ID]
    with patch.object(controller, "_observe_characteristics", side_effect=AccessoryDisconnectedError("rebooting")):
        # a failure would make the Hub drop the device, the accessory staying paired to it
        await controller.pair_device(discovery, ProvidedCredentials(type=CredentialsType.code, value="031-45-154"))
    assert server.data.is_paired and DEVICE_ID not in controller.discoveries
    assert "rebooting" in caplog.text
    async with repository() as repo:
        device = await repo.get(DEVICE_ID, as_=HKDevice)
    assert device is not None and device.integration_data.pairing_data


async def test_pair_device_rejects_wrong_credentials_type(unpaired_server, controller):
    await unpaired_server()
    await _wait_for(lambda: DEVICE_ID in controller.discoveries)
    discovery = controller.discoveries[DEVICE_ID]
    with pytest.raises(ValueError):
        await controller.pair_device(discovery, ProvidedCredentials(type=CredentialsType.qr, value="x"))


async def test_drops_its_discoveries_when_it_stops(unpaired_server, controller, repository):
    server = await unpaired_server()
    await _wait_for(lambda: DEVICE_ID in controller.discoveries)
    discovery = controller.discoveries[DEVICE_ID]

    await controller.stop()
    assert controller.discoveries == {}
    # a discovery the Hub still holds can't pair through the stopped controller
    async with repository() as repo:
        await repo.save(provisional_device())
    with pytest.raises(KeyError):
        await controller.pair_device(discovery, ProvidedCredentials(type=CredentialsType.code, value="031-45-154"))
    assert not server.data.is_paired


async def test_stop_cancels_a_discovery_still_being_handled(unpaired_server, controller, output):
    await unpaired_server()
    await _wait_for(lambda: DEVICE_ID in controller.discoveries)
    (discovery,) = controller._aiohomekit.discoveries.values()
    output.received_discoveries.clear()

    controller._aiohomekit_did_discover(controller._aiohomekit, discovery)  # aiohomekit's callback, handled in a task
    await controller.stop()
    await asyncio.sleep(0.1)
    assert output.received_discoveries == [] and controller.discoveries == {}


@needs_aiohomekit_lifetime_fixes
async def test_ignores_a_discovery_aiohomekit_resolves_after_the_stop(unpaired_server, controller, output):
    await unpaired_server()
    await _wait_for(lambda: DEVICE_ID in controller.discoveries)
    output.received_discoveries.clear()

    class SlowInfo(MockedAsyncServiceInfo):
        async def async_request(self, *args, **kwargs):
            await asyncio.sleep(0.3)  # the accessory answers late; aiohomekit waits up to 3 s
            return await super().async_request(*args, **kwargs)

    # what aiohomekit spawns, untracked, for a zeroconf update whose records aren't all cached
    transport = controller._aiohomekit._transports[TransportType.IP]
    info = SlowInfo(HAP_TYPE_TCP, f"Testlicht.{HAP_TYPE_TCP}")
    resolving = asyncio.create_task(transport._handle_discovery_service(info))
    await asyncio.sleep(0.05)
    await controller.stop()
    await resolving
    await asyncio.sleep(0.1)
    assert output.received_discoveries == [] and controller.discoveries == {}


async def test_logs_what_fails_in_the_background(controller, output, caplog):
    output.controller_did_receive_events = AsyncMock(side_effect=RuntimeError("the Hub is gone"))
    controller._run_handle_accessory_response(PAIRING_DATA["AccessoryPairingID"], {(1, 9): {"value": True}})
    await _wait_for(lambda: output.controller_did_receive_events.await_count == 1)
    await asyncio.sleep(0)
    assert any(r.name == "majordom_homekit.controller" and "the Hub is gone" in r.getMessage() for r in caplog.records)


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
        integration=HomeKitController.slug(),
        manufacturer="lusiardi.de",
        integration_data=HKDeviceIntegrationData(pairing_data=pairing_data, characteristics_cache=None),
    )


async def test_unpairs_a_device(paired_server, controller, output, repository):
    server, pairing_data = paired_server
    await _wait_for(lambda: DEVICE_ID in output.connected_devices)
    assert server.data.is_paired

    await controller.unpair(_hk_device(pairing_data))
    assert not server.data.is_paired
    # the Hub's soft delete keeps the row: a pairing left in it would be loaded again on the next start
    async with repository() as repo:
        device = await repo.get(DEVICE_ID, as_=HKDevice)
    assert device is not None and device.integration_data.pairing_data is None


async def test_forgets_an_accessory_it_cant_reach_to_unpair(paired_server, controller, output, repository, caplog):
    server, pairing_data = paired_server
    await _wait_for(lambda: DEVICE_ID in output.connected_devices)
    await _cut_off(server, controller._aiohomekit.pairings[HK_ID])  # the bulb broke or went in the bin

    with patch(CONNECT_TIMEOUT, lambda _: asyncio.timeout(0.3)):
        await controller.unpair(_hk_device(pairing_data))  # the user deletes it in the app
    assert "reset" in caplog.text
    assert _reconnect_loops() == []  # its session doesn't come back if the bulb does
    async with repository() as repo:
        device = await repo.get(DEVICE_ID, as_=HKDevice)
    assert device is not None
    assert device.integration_data.pairing_data is None and device.integration_data.characteristics_cache is None


async def test_reports_a_re_paired_accessory_connected(unpaired_server, controller, output, repository):
    await unpaired_server()
    await _wait_for(lambda: DEVICE_ID in controller.discoveries)
    async with repository() as repo:
        await repo.save(provisional_device())
    code = ProvidedCredentials(type=CredentialsType.code, value="031-45-154")
    await controller.pair_device(controller.discoveries[DEVICE_ID], code)
    async with repository() as repo:
        device = await repo.get(DEVICE_ID, as_=HKDevice)
    assert device is not None
    await controller.unpair(device)  # the Hub then shows it unavailable
    assert controller._characteristics_observers == {}
    output.connected_devices.clear()

    (discovery,) = controller._aiohomekit.discoveries.values()
    await controller._async_aiohomekit_did_discover(controller._aiohomekit, discovery)  # offered again
    await controller.pair_device(controller.discoveries[DEVICE_ID], code)  # it keeps its HAP id, so its device id
    assert DEVICE_ID in output.connected_devices


async def test_sends_a_command_to_the_device(paired_server, controller, output):
    _, pairing_data = paired_server
    await _wait_for(lambda: DEVICE_ID in output.connected_devices)

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


async def test_a_command_the_device_refuses_fails(paired_server, controller, output):
    _, pairing_data = paired_server
    await _wait_for(lambda: DEVICE_ID in output.connected_devices)

    with pytest.raises(ValueError, match="1.10"):
        await controller.send_command(
            DeviceCommand(device_id=DEVICE_ID, parameter_id=BRIGHTNESS_PARAM_ID, value=1000),  # brightness is 0-100
            _hk_device(pairing_data),
            _brightness_parameter(),
        )


async def test_names_a_device_whose_pairing_isnt_loaded(controller):
    device = _hk_device(PAIRING_DATA)  # e.g. its stored pairing failed to load
    with pytest.raises(RuntimeError, match=HK_ID):
        await controller.fetch(device)
    with pytest.raises(RuntimeError, match=HK_ID):
        command = DeviceCommand(device_id=DEVICE_ID, parameter_id=BRIGHTNESS_PARAM_ID, value=1)
        await controller.send_command(command, device, _brightness_parameter())


async def test_reports_the_good_values_of_a_batch_with_a_bad_status(controller, output, caplog):
    await controller._handle_accessory_response(
        PAIRING_DATA["AccessoryPairingID"], {(1, 9): {"value": True}, (1, 10): {"status": -70402}}
    )
    assert [(e.parameter_id, e.value) for e in output.events] == [(ON_PARAM_ID, True)]
    assert '"1.10"' in caplog.text


async def test_reports_device_state_as_events_on_connect(paired_server, controller, output):
    # The device -> Hub reporting path: on connecting to a paired accessory the controller
    # reads its characteristics and reports each as a DeviceParameterChange. (This is what the
    # Hub's e2e test_events actually exercises — it uses value == the initial, so it never
    # distinguished a pushed change; the mock accessory server doesn't deliver async pushes
    # to the observer in-process. The reporting *channel* is what matters and is covered here.)
    _, pairing_data = paired_server
    await _wait_for(lambda: DEVICE_ID in output.connected_devices)

    await _wait_for(lambda: any(e.parameter_id == ON_PARAM_ID for e in output.events))
    on_events = [e for e in output.events if e.parameter_id == ON_PARAM_ID]
    assert on_events[-1].value is False  # the accessory's ON characteristic starts False


async def test_reports_an_accessory_connected_only_once_it_answers(paired_server, controller, output):
    server, _ = paired_server
    await _wait_for(lambda: DEVICE_ID in output.connected_devices)
    await _cut_off(server, controller._aiohomekit.pairings[HK_ID])
    await controller._set_availability(DEVICE_ID, False)  # what the availability poll reports within 30 s
    output.connected_devices.clear()

    (discovery,) = controller._aiohomekit.discoveries.values()
    with patch(CONNECT_TIMEOUT, lambda _: asyncio.timeout(0.3)), pytest.raises(AccessoryDisconnectedError):
        await controller._async_aiohomekit_did_discover(controller._aiohomekit, discovery)  # its mDNS answers on
    assert DEVICE_ID not in output.connected_devices


async def test_reports_a_pushed_change_once_however_often_rediscovered(paired_server, controller, output):
    await _wait_for(lambda: DEVICE_ID in output.connected_devices)
    (discovery,) = controller._aiohomekit.discoveries.values()
    for _ in range(3):  # each zeroconf update of the accessory (s#, c#, address) reports it again
        await controller._async_aiohomekit_did_discover(controller._aiohomekit, discovery)

    pairing = controller._aiohomekit.pairings[HK_ID]
    pairing._callback_characteristic_changed({CharacteristicKey(1, 9): {"value": True}})  # what a push from it runs
    await _wait_for(lambda: any(e.parameter_id == ON_PARAM_ID and e.value is True for e in output.events))
    await asyncio.sleep(0.1)
    assert [e.value for e in output.events if e.parameter_id == ON_PARAM_ID].count(True) == 1


async def test_saves_the_data_model_without_duplicating_parameters(paired_server, controller, output, repository):
    await _wait_for(lambda: DEVICE_ID in output.connected_devices)
    accessories = controller._aiohomekit.pairings[HK_ID].accessories_state
    for _ in range(2):  # aiohomekit saves it on every newer c# of the accessory, e.g. after each start
        await controller.hk_char_storage.save(HK_ID, accessories)

    async with repository() as repo:
        device = await repo.state(DEVICE_ID, as_=HKDeviceState)
    assert device is not None
    ids = [p.id for p in device.parameters]
    assert ON_PARAM_ID in ids and len(ids) == len(set(ids))


async def test_fetch_reports_the_device_state(paired_accessory, controller, output):
    # Not advertised: aiohomekit loads stored pairings without connecting, so this read fetches the data model first
    _, pairing_data = paired_accessory
    await controller.fetch(_hk_device(pairing_data))
    assert any(e.parameter_id == ON_PARAM_ID and e.value is False for e in output.events)


async def test_identify(paired_server, controller, output):
    _, pairing_data = paired_server
    await _wait_for(lambda: DEVICE_ID in output.connected_devices)
    # smoke: identify reaches the accessory without error
    await controller.identify(_hk_device(pairing_data))
