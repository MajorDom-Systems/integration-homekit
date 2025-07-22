import asyncio
import errno
import socket
import tempfile
import threading
from uuid import UUID, uuid5

import pytest
import pytest_asyncio
from aiohomekit.model.accessories import Accessory
from aiohomekit.model.characteristics import CharacteristicsTypes
from aiohomekit.model.services import ServicesTypes
from aiohomekit.testing.accessoryserver import AccessoryServer

from majordom_hub.models.device import Device
from majordom_hub.utils.database import create_async_session

HAP_TYPE_TCP = "_hap._tcp.local."
HAP_TYPE_UDP = "_hap._udp.local."
TYPE_PTR = 12
CLASS_IN = 1

def _get_test_socket() -> socket.socket:
    """Create a socket to test binding ports."""
    test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    test_socket.setblocking(False)
    test_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    return test_socket

def port_ready(port: int) -> bool:
    try:
        _get_test_socket().bind(("127.0.0.1", port))
    except OSError as e:
        if e.errno == errno.EADDRINUSE:
            return True

    return False

def next_available_port() -> int:
    for port in range(51842, 53842):
        if not port_ready(port):
            return port

    raise RuntimeError("No available ports")

async def wait_for_server_online(port: int):
    for _ in range(100):
        if port_ready(port):
            break
        await asyncio.sleep(0.025)

@pytest.fixture()
def id_factory():
    id_counter = 0

    def _get_id():
        nonlocal id_counter
        id_counter += 1
        return id_counter

    yield _get_id

@pytest_asyncio.fixture
async def start_accessory_server(id_factory):
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

    async def start():
        t.start()
        await wait_for_server_online(available_port)
        assert not accessory_server.data.is_paired
        return accessory_server

    yield start

    async with create_async_session() as session:
        if device := await session.get(Device, uuid5(UUID(int=0), '12:34:56:00:01:0A')):
            await session.delete(device)
            await session.commit()

@pytest_asyncio.fixture
async def paired_accessory_server(id_factory, crud):
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

    pairing_data = {
        'AccessoryPairingID': '12:34:56:00:01:0A',
        'AccessoryLTPK': '7986cf939de8986f428744e36ed72d86189bea46b4dcdc8d9d79a3e4fceb92b9',
        'AccessoryLTSK': '3d99f3e959a1f93af4056966f858074b2a1fdec1c5fd84a51ea96f9fa004156a',
        'iOSDeviceId': 'decc6fa3-de3e-41c9-adba-ef7409821bfc',
        'iOSDeviceLTPK': 'd708df2fbf4a8779669f0ccd43f4962d6d49e4274f88b1292f822edc3bcf8ed8',
        'iOSDeviceLTSK': 'fa45f082ef87efc6c8c8d043d74084a3ea923a2253e323a7eb9917b4090c2fcc',
        'Connection': 'IP',
        'AccessoryIP': '127.0.0.1',
        'AccessoryPort': available_port
    }

    async with create_async_session() as session:
        device = Device(
            id=uuid5(UUID(int=0), '12:34:56:00:01:0A'),
            integration='homekit',
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
            }
        )
        session.add(device)
        await session.commit()

    t.start()
    await wait_for_server_online(available_port)
    assert accessory_server.data.is_paired

    yield accessory_server, pairing_data

    async with create_async_session() as session:
        if device := await session.get(Device, uuid5(UUID(int=0), '12:34:56:00:01:0A')):
            await session.delete(device)
            await session.commit()

if __name__ == '__main__':
    accessory = Accessory.create_with_info(
        aid=0,
        name="Testlicht",
        manufacturer="lusiardi.de",
        model="Demoserver",
        serial_number="0001",
        firmware_revision="0.1"
    )
    lightBulbService = accessory.add_service(ServicesTypes.LIGHTBULB)
    lightBulbService.add_char(CharacteristicsTypes.ON, value=False)
    lightBulbService.add_char(CharacteristicsTypes.BRIGHTNESS, value=0)

    print('\n\n\n Accessory: ')
    from pprint import pprint ; pprint(accessory.as_dict())
    print('\n---------------------------\n\n')
