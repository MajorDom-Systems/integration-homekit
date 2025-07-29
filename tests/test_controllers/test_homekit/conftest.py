import socket
import tempfile
import threading
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid5

import pytest
import pytest_asyncio
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

from majordom_hub.models.device import Device
from majordom_hub.models.parameter import Parameter, ParameterState
from majordom_hub.schemas.parameter import (
    ParameterDataType,
    ParameterRole,
    ParameterUnit,
)
from majordom_hub.utils.database import create_async_session

HAP_TYPE_TCP = "_hap._tcp.local."
HAP_TYPE_UDP = "_hap._udp.local."
TYPE_PTR = 12
CLASS_IN = 1


def get_mock_service_info(port: int, is_paired: bool) -> MockedAsyncServiceInfo:
    desc = {
        b'c#': b'1',                     # Config number
        b'id': b'12:34:56:00:01:0A',     # Pairing ID
        b'md': b'Demoserver',            # Model
        b's#': b'1',                     # State number
        b'ci': b'5',                     # Category (Lightbulb)
        b'sf': b'0' if is_paired else b'1',  # Status Flag (discoverable if paired)
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

@pytest.fixture
def mock_zeroconf():
    with (
        patch("zeroconf.asyncio.AsyncServiceBrowser", AsyncServiceBrowserStub),
        patch("zeroconf.asyncio.AsyncZeroconf") as mock_zc,
        patch("majordom_hub.coordinator.AsyncServiceBrowser", AsyncServiceBrowserStub),
        patch("majordom_hub.coordinator.AsyncZeroconf", mock_zc),
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


@pytest.fixture()
def id_factory():
    id_counter = 0

    def _get_id():
        nonlocal id_counter
        id_counter += 1
        return id_counter

    yield _get_id

@pytest_asyncio.fixture
async def start_accessory_server(id_factory, mock_zeroconf):
    '''Returns start function'''

    available_port = next_available_port()

    config_file = tempfile.NamedTemporaryFile(delete=False)
    data = b"""{
        "accessory_ltpk": "7986cf939de8986f428744e36ed72d86189bea46b4dcdc8d9d79a3e4fceb92b9",
        "accessory_ltsk": "3d99f3e959a1f93af4056966f858074b2a1fdec1c5fd84a51ea96f9fa004156a",
        "accessory_pairing_id": "12:34:56:00:01:0A",
        "accessory_pin": "031-45-154",
        "c#": 1,
        "category": "Lightbulb",
        "host_ip": "127.0.0.1",
        "host_port": %port%,
        "name": "unittestLight",
        "peers": {},
        "unsuccessful_tries": 0
    }""".replace(
        b"%port%", str(available_port).encode("utf-8")
    )

    config_file.write(data)
    config_file.close()

    accessory_server = AccessoryServer(config_file.name, None)
    accessory = Accessory.create_with_info(
        aid=id_factory(),
        name="Testlicht",
        manufacturer="lusiardi.de",
        model="Demoserver",
        serial_number="0001",
        firmware_revision="0.1"
    )
    lightBulbService = accessory.add_service(ServicesTypes.LIGHTBULB)
    lightBulbService.add_char(CharacteristicsTypes.ON, value=False)
    accessory_server.add_accessory(accessory)

    t = threading.Thread(target=accessory_server.serve_forever, daemon=True)

    service_info = get_mock_service_info(available_port, is_paired=False)

    async def start():
        t.start()
        await wait_for_server_online(available_port)
        print(f"Server started at http://127.0.0.1:{available_port}")
        assert not accessory_server.data.is_paired
        return accessory_server

    with install_mock_service_info(mock_zeroconf, service_info):
        yield start

    # cleanup after test

    accessory_server.shutdown()
    t.join()

    async with create_async_session() as session:
        if device := await session.get(Device, UUID('70c3b8fa-709d-5e1b-8ea9-a12bb0a24fac')):
            await session.delete(device)
            await session.commit()

@pytest.fixture
def get_pairing_data():
    def _make_pairing_data(available_port: int) -> dict[str, str | int]:
        return {
            'AccessoryPairingID': '12:34:56:00:01:0A',
            'AccessoryLTPK': '7986cf939de8986f428744e36ed72d86189bea46b4dcdc8d9d79a3e4fceb92b9',
            'AccessoryLTSK': '3d99f3e959a1f93af4056966f858074b2a1fdec1c5fd84a51ea96f9fa004156a',
            'iOSDeviceId': 'decc6fa3-de3e-41c9-adba-ef7409821bfc',
            'iOSDeviceLTPK': 'd708df2fbf4a8779669f0ccd43f4962d6d49e4274f88b1292f822edc3bcf8ed8',
            'iOSDeviceLTSK': 'fa45f082ef87efc6c8c8d043d74084a3ea923a2253e323a7eb9917b4090c2fcc',
            'Connection': 'IP',
            'AccessoryAddress': '127.0.0.1',
            'AccessoryPort': available_port
        }
    return _make_pairing_data

@pytest_asyncio.fixture
async def paired_accessory_server(id_factory, crud, mock_zeroconf, get_pairing_data):
    room = await crud.create_room()

    available_port = next_available_port()

    config_file = tempfile.NamedTemporaryFile(delete=False)
    data = b"""{
        "accessory_ltpk": "7986cf939de8986f428744e36ed72d86189bea46b4dcdc8d9d79a3e4fceb92b9",
        "accessory_ltsk": "3d99f3e959a1f93af4056966f858074b2a1fdec1c5fd84a51ea96f9fa004156a",
        "accessory_pairing_id": "12:34:56:00:01:0A",
        "accessory_pin": "031-45-154",
        "c#": 1,
        "category": "Lightbulb",
        "host_ip": "127.0.0.1",
        "host_port": %port%,
        "name": "unittestLight",
        "peers": {
            "decc6fa3-de3e-41c9-adba-ef7409821bfc": {
                "admin": true,
                "key": "d708df2fbf4a8779669f0ccd43f4962d6d49e4274f88b1292f822edc3bcf8ed8"
            }
        },
        "unsuccessful_tries": 0
    }""".replace(
        b"%port%", str(available_port).encode("utf-8")
    )

    config_file.write(data)
    config_file.close()

    accessory_server = AccessoryServer(config_file.name, None)
    accessory = Accessory.create_with_info(
        aid=id_factory(),
        name="Testlicht",
        manufacturer="lusiardi.de",
        model="Demoserver",
        serial_number="0001",
        firmware_revision="0.1"
    )
    lightBulbService = accessory.add_service(ServicesTypes.LIGHTBULB)
    lightBulbService.add_char(CharacteristicsTypes.ON, value=False)
    lightBulbService.add_char(CharacteristicsTypes.BRIGHTNESS, value=0)
    accessory_server.add_accessory(accessory)

    # print('\n\n\n Accessory: ')
    # from pprint import pprint ; pprint(accessory.as_dict())
    # print('\n---------------------------\n\n')

    t = threading.Thread(target=accessory_server.serve_forever, daemon=True)

    # prepare hub

    pairing_data = get_pairing_data(available_port)

    async with create_async_session() as session:
        session.add(Parameter(
            id = uuid5(UUID('70c3b8fa-709d-5e1b-8ea9-a12bb0a24fac'), '1.10'),
            name = 'Is On',
            data_type = ParameterDataType.integer,
            unit = ParameterUnit.plain,
            role = ParameterRole.control,
            min_value = 0,
            max_value = 100,
            min_step = 1,
            integration_data = {
                'type': UUID(CharacteristicsTypes.BRIGHTNESS),
                'aid': 1,
                'iid': 10,
            }
        ))
        session.add(Parameter(
            id = uuid5(UUID('70c3b8fa-709d-5e1b-8ea9-a12bb0a24fac'), '1.9'),
            name = 'Is On',
            data_type = ParameterDataType.bool,
            unit = ParameterUnit.plain,
            role = ParameterRole.control,
            integration_data = {
                'type': UUID(CharacteristicsTypes.ON),
                'aid': 1,
                'iid': 9,
            }
        ))
        session.add(Device(
            id=UUID('70c3b8fa-709d-5e1b-8ea9-a12bb0a24fac'),
            integration='HomeKit',
            transport='IP',
            manufacturer='',
            name='',
            category=None,
            icon=None,
            note='',
            room_id=room.id,
            integration_data={
                'pairing_data': pairing_data,
                'characteristics_cache': {}
            },
            parameters=[
                ParameterState(
                    device_id=UUID('70c3b8fa-709d-5e1b-8ea9-a12bb0a24fac'),
                    parameter_id=uuid5(UUID('70c3b8fa-709d-5e1b-8ea9-a12bb0a24fac'), '1.9'),
                ),
                ParameterState(
                    device_id=UUID('70c3b8fa-709d-5e1b-8ea9-a12bb0a24fac'),
                    parameter_id=uuid5(UUID('70c3b8fa-709d-5e1b-8ea9-a12bb0a24fac'), '1.10'),
                ),
            ]
        ))
        await session.commit()

    service_info = get_mock_service_info(available_port, is_paired=True)
    t.start()
    await wait_for_server_online(available_port)
    assert accessory_server.data.is_paired

    with install_mock_service_info(mock_zeroconf, service_info):
        yield accessory_server, pairing_data

    # cleanup after test

    accessory_server.shutdown()
    t.join()

    async with create_async_session() as session:
        if device := await session.get(Device, UUID('70c3b8fa-709d-5e1b-8ea9-a12bb0a24fac')):
            await session.delete(device)
            await session.commit()
