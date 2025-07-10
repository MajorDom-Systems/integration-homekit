
# end-to-end test

# DONE: run full hub app - done, coordinator fixture
# DONE: run virtual homekit device server - done, accessory_server fixture
# DONE: implement a new client service that will send user-targeted messages to connected clients
# DONE: rename current client service to cloud service, and
# DONE: client.websocket_connect to connect as a client to hub and receive user-targeted messages
# DONE: mock cloud_service's send method to catch cloud-targeted ws messages
# TODO: mock all system, hardware, and network for all tests
# TODO: add auth

# test discovery
# test pairing
# test unpairing
# test control
# test events

import json
from uuid import uuid5

from fastapi.testclient import TestClient

from majordom_hub.schemas.device import Discovery

{
    "accessory_ltpk": "7986cf939de8986f428744e36ed72d86189bea46b4dcdc8d9d79a3e4fceb92b9",
    "accessory_ltsk": "3d99f3e959a1f93af4056966f858074b2a1fdec1c5fd84a51ea96f9fa004156a",
    "accessory_pairing_id": "12:34:56:00:01:0A",
    "accessory_pin": "031-45-154",
    "c#": 1,
    "category": "Lightbulb",
    "host_ip": "127.0.0.1",
    "host_port": '',
    "name": "unittestLight",
    "peers": {
        "decc6fa3-de3e-41c9-adba-ef7409821bfc": {
            "admin": 'true',
            "key": "d708df2fbf4a8779669f0ccd43f4962d6d49e4274f88b1292f822edc3bcf8ed8"
        }
    },
    "unsuccessful_tries": 0
} # type: ignore

async def test_discovery(cloud_service_mock, coordinator, start_accessory_server):

    expected_discovery = Discovery(
        id=uuid5(UUID(int=0), '12:34:56:00:01:0A'),
        controller='homekit',
        credentials='code',
        expiration=None,
        transport='ip',
        device_manufacturer=None,
        device_name='unittestLight',
        device_category='Lightbulb',
        device_icon=None,
    ).dict()
    expected_message = {'type': 'majordom_did_discover_discovery', 'data': expected_discovery}

    client = TestClient(coordinator.server_service.app)

    current_discoveries = client.get('/discoveries') # TODO: check endpoints
    assert current_discoveries.status_code == 200
    assert current_discoveries.json() == []

    with client.websocket_connect('/ws') as ws:
        await start_accessory_server()
        data = ws.receive_json()
        assert data == expected_message

    new_discoveries = client.get('/discoveries')
    assert new_discoveries.status_code == 200
    assert new_discoveries.json() == expected_discovery
    assert cloud_service_mock.return_value.send_message.assert_awaited_with(json.dumps(expected_message))

async def test_pairing(coordinator, start_accessory_server):
    start_accessory_server()
    client = TestClient(coordinator.server_service.app)

    r = client.post('/device')
    assert r.status_code == 200

    saved_device = device_repo.get(r.json()['id'])
    assert saved_device is not None
    # TODO: check all props here

    # cleanup: delete device

async def test_unpairing(coordinator, start_accessory_server):
    # TODO: paired accessory fixture
    start_accessory_server()
    crud.create_device()

    client = TestClient(coordinator.server_service.app)
    client.delete(f'/device/{device_id}')
    assert client.status_code == 200
    assert device_repo.get(device_id) is None
    # assert accessory_server TODO

async def test_control():
    ...

async def test_events():
    ...
