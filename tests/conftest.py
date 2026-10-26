"""Unit tests for the HomeKit controller.

These drive `HomeKitController` directly — via the SDK's test platform, against
aiohomekit's in-process virtual accessory server with a mocked zeroconf — so they test the
integration on its own, with no Hub. The Hub keeps the e2e coverage (Coordinator + API/ws).
"""

import socket
import tempfile
import threading
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid5

import pytest
import pytest_asyncio
from aiohomekit.controller.abstract import AbstractPairing
from aiohomekit.model.accessories import Accessory
from aiohomekit.model.characteristics import CharacteristicsTypes
from aiohomekit.model.services import ServicesTypes
from aiohomekit.testing.accessoryserver import AccessoryServer
from aiohomekit.testing.mock_zeroconf import (
    AsyncServiceBrowserStub,
    DNSCache,
    MockedAsyncServiceInfo,
    install_mock_service_info,
)
from aiohomekit.testing.utils import next_available_port, wait_for_server_online
from majordom_integration_sdk import Peripherals
from majordom_integration_sdk.runtime.peripherals.providers.zeroconf import ZeroconfDiscoveryService
from majordom_integration_sdk.testing import RecordingControllerOutput, build_test_platform

from majordom_homekit import HomeKitController
from majordom_homekit.models import HKDeviceIntegrationData, HKDeviceState

HAP_TYPE_TCP = "_hap._tcp.local."
ZEROCONF = "majordom_integration_sdk.runtime.peripherals.providers.zeroconf"

# The device id the accessory (pairing id 12:34:56:00:01:0A) maps to under HomeKit's slug —
# uuid5(uuid5(namespace, "homekit"), "12:34:56:00:01:0a"). Computed the same way the mapper does.
INTEGRATION_UUID = uuid5(UUID(int=0), "homekit")
DEVICE_ID = uuid5(INTEGRATION_UUID, "12:34:56:00:01:0a")
ON_PARAM_ID = uuid5(DEVICE_ID, "1.9")
BRIGHTNESS_PARAM_ID = uuid5(DEVICE_ID, "1.10")
HK_ID = "12:34:56:00:01:0a"  # aiohomekit's pairing key

# parker-aiohomekit 4.1.0 (unreleased) loads stored pairings without connecting and closes them on stop
needs_aiohomekit_lifetime_fixes = pytest.mark.skipif(
    not hasattr(AbstractPairing, "restore_accessories_state"), reason="needs parker-aiohomekit 4.1.0"
)


def provisional_device(pairing_data=None) -> HKDeviceState:
    """A device row as the Hub has it *before* handing control to the integration: identity
    and integration_data present, parameters still empty (the controller fills them)."""
    return HKDeviceState(
        id=DEVICE_ID,
        name="Testlicht",
        room_id=UUID(int=1),
        transport="IP",
        integration=HomeKitController.slug(),
        manufacturer="",
        parameters=[],
        integration_data=HKDeviceIntegrationData(pairing_data=pairing_data, characteristics_cache=None),
    )


def get_mock_service_info(port: int, is_paired: bool) -> MockedAsyncServiceInfo:
    desc = {
        b"c#": b"1",
        b"id": b"12:34:56:00:01:0A",
        b"md": b"Demoserver",
        b"s#": b"1",
        b"ci": b"5",
        b"sf": b"0" if is_paired else b"1",
    }
    return MockedAsyncServiceInfo(
        HAP_TYPE_TCP,
        f"Testlicht.{HAP_TYPE_TCP}",
        addresses=[socket.inet_aton("127.0.0.1")],
        port=port,
        properties=desc,
        weight=0,
        priority=0,
    )


@pytest.fixture(autouse=True)
def mock_zeroconf():
    with (
        patch(f"{ZEROCONF}.AsyncServiceBrowser", AsyncServiceBrowserStub),
        patch(f"{ZEROCONF}.AsyncZeroconf") as mock_zc,
        patch("zeroconf.asyncio.AsyncServiceBrowser", AsyncServiceBrowserStub),
        patch("zeroconf.asyncio.AsyncZeroconf", mock_zc),
        patch("aiohomekit.controller.zeroconf.controller.AsyncServiceInfo", MockedAsyncServiceInfo),
    ):
        zc = mock_zc.return_value
        zc.register_service = AsyncMock()
        zc.async_close = AsyncMock()
        zeroconf = MagicMock(name="zeroconf_mock")
        zeroconf.cache = DNSCache()
        zeroconf.async_wait_for_start = AsyncMock()
        zeroconf.listeners = [AsyncServiceBrowserStub()]
        zc.zeroconf = zeroconf
        with patch("aiohomekit.testing.accessoryserver.Zeroconf", zc):
            yield zc


@pytest.fixture
def id_factory():
    counter = 0

    def _get_id():
        nonlocal counter
        counter += 1
        return counter

    return _get_id


PAIRING_DATA = {
    "AccessoryPairingID": "12:34:56:00:01:0A",
    "AccessoryLTPK": "7986cf939de8986f428744e36ed72d86189bea46b4dcdc8d9d79a3e4fceb92b9",
    "AccessoryLTSK": "3d99f3e959a1f93af4056966f858074b2a1fdec1c5fd84a51ea96f9fa004156a",
    "iOSDeviceId": "decc6fa3-de3e-41c9-adba-ef7409821bfc",
    "iOSDeviceLTPK": "d708df2fbf4a8779669f0ccd43f4962d6d49e4274f88b1292f822edc3bcf8ed8",
    "iOSDeviceLTSK": "fa45f082ef87efc6c8c8d043d74084a3ea923a2253e323a7eb9917b4090c2fcc",
    "Connection": "IP",
    "AccessoryAddress": "127.0.0.1",
}

_ACCESSORY_CONFIG = b"""{
    "accessory_ltpk": "7986cf939de8986f428744e36ed72d86189bea46b4dcdc8d9d79a3e4fceb92b9",
    "accessory_ltsk": "3d99f3e959a1f93af4056966f858074b2a1fdec1c5fd84a51ea96f9fa004156a",
    "accessory_pairing_id": "12:34:56:00:01:0A",
    "accessory_pin": "031-45-154",
    "c#": 1, "category": "Lightbulb", "host_ip": "127.0.0.1", "host_port": %port%,
    "name": "unittestLight", "peers": %peers%, "unsuccessful_tries": 0
}"""


def _make_accessory_server(id_factory, port: int, peers: bytes, with_brightness: bool) -> AccessoryServer:
    config_file = tempfile.NamedTemporaryFile(delete=False)  # noqa: SIM115 (outlives fn; AccessoryServer reads it by path)
    config_file.write(_ACCESSORY_CONFIG.replace(b"%port%", str(port).encode()).replace(b"%peers%", peers))
    config_file.close()
    server = AccessoryServer(config_file.name, None)
    accessory = Accessory.create_with_info(
        aid=id_factory(),
        name="Testlicht",
        manufacturer="lusiardi.de",
        model="Demoserver",
        serial_number="0001",
        firmware_revision="0.1",
    )
    bulb = accessory.add_service(ServicesTypes.LIGHTBULB)
    bulb.add_char(CharacteristicsTypes.ON, value=False)
    if with_brightness:
        bulb.add_char(CharacteristicsTypes.BRIGHTNESS, value=0)
    server.add_accessory(accessory)
    return server


@pytest.fixture
def repository(platform):
    """A unit of work on the in-memory device repository, scoped to HomeKit as the controller's."""
    return lambda: platform.make_device_repository(HomeKitController.slug())


@pytest_asyncio.fixture
async def zeroconf(mock_zeroconf):
    zeroconf_service = ZeroconfDiscoveryService()
    await zeroconf_service.start()  # under mock_zeroconf, so async_zeroconf yields the mock
    yield zeroconf_service
    await zeroconf_service.stop()


@pytest.fixture
def platform(tmp_path):
    return build_test_platform(tmp_path)


@pytest.fixture
def output():
    return RecordingControllerOutput()


@pytest_asyncio.fixture
async def controller(platform, zeroconf, output):
    controller = HomeKitController(platform)
    controller.output = output
    controller.peripherals = Peripherals({"mdns": zeroconf.endpoint})
    await controller.start()
    yield controller
    await controller.stop()


@pytest_asyncio.fixture
async def unpaired_server(id_factory, mock_zeroconf):
    port = next_available_port()
    server = _make_accessory_server(id_factory, port, peers=b"{}", with_brightness=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    service_info = get_mock_service_info(port, is_paired=False)

    async def start():
        thread.start()
        await wait_for_server_online(port)
        assert not server.data.is_paired
        return server

    with install_mock_service_info(mock_zeroconf, service_info):
        yield start
    server.shutdown()
    thread.join()


@pytest_asyncio.fixture
async def paired_accessory(id_factory, repository):
    """A pre-paired accessory + a HomeKit device seeded into the repository the way the Hub
    would have after pairing, not advertised over zeroconf."""
    port = next_available_port()
    peers = (
        b'{"decc6fa3-de3e-41c9-adba-ef7409821bfc": {"admin": true,'
        b' "key": "d708df2fbf4a8779669f0ccd43f4962d6d49e4274f88b1292f822edc3bcf8ed8"}}'
    )
    server = _make_accessory_server(id_factory, port, peers=peers, with_brightness=True)

    pairing_data = {**PAIRING_DATA, "AccessoryPort": port}
    async with repository() as repo:
        await repo.save(provisional_device(pairing_data))

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    await wait_for_server_online(port)
    assert server.data.is_paired

    yield server, pairing_data
    server.shutdown()
    thread.join()


@pytest.fixture
def paired_server(paired_accessory, mock_zeroconf):
    """The pre-paired accessory, advertised over zeroconf."""
    _, pairing_data = paired_accessory
    with install_mock_service_info(mock_zeroconf, get_mock_service_info(pairing_data["AccessoryPort"], is_paired=True)):
        yield paired_accessory
