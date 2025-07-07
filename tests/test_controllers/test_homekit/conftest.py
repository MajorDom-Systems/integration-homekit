import asyncio
import errno
import socket
import tempfile
import threading

import pytest
from aiohomekit.model.accessories import Accessory
from aiohomekit.model.characteristics import CharacteristicsTypes
from aiohomekit.model.services import ServicesTypes
from aiohomekit.testing import AccessoryServer

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

@pytest.fixture
async def accessory_server():
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

    httpd = AccessoryServer(config_file.name, None)
    accessory = Accessory.create_with_info(
        id=id_factory(),
        name="Testlicht",
        manufacturer="lusiardi.de",
        model="Demoserver",
        serial_number="0001",
        firmware_revision="0.1"
    )
    lightBulbService = accessory.add_service(ServicesTypes.LIGHTBULB)
    lightBulbService.add_char(CharacteristicsTypes.ON, value=False)
    httpd.add_accessory(accessory)

    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()

    await wait_for_server_online(available_port)
