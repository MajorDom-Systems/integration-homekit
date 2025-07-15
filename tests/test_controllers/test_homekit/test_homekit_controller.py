# end-to-end test

import json
import random
from uuid import UUID, uuid4, uuid5

from aiohomekit.controller.zeroconf.ip import IpPairing
from fastapi.testclient import TestClient

from majordom_hub.models.device import Device
from majordom_hub.utils.database import create_async_session


async def test_discover_unpaired(cloud_service_mock, coordinator, start_accessory_server, crud, get_user_bearer):
    user = await crud.create_user()

    expected_discovery = {
        'id': str(uuid5(UUID(int=0), '12:34:56:00:01:0A')),
        'controller': 'homekit',
        'credentials': 'code',
        'expiration': None,
        'transport': 'ip',
        # device_manufacturer='lusiardi.de',
        'device_manufacturer': None, # it's available only after pairing
        'device_name': 'Testlicht',
        'device_category': 'Lightbulb',
        'device_icon': None,
    }
    expected_message = {'type': 'majordom_did_discover_discovery', 'data': expected_discovery}

    client = TestClient(coordinator.server_service.app)

    current_discoveries = client.get('/device/discoveries', headers = get_user_bearer(user.id))
    assert current_discoveries.status_code == 200
    assert current_discoveries.json() == []

    with client.websocket_connect('/ws') as ws:
        await start_accessory_server()
        data = ws.receive_json()
        assert data == expected_message

    new_discoveries = client.get('/device/discoveries', headers = get_user_bearer(user.id))
    assert new_discoveries.status_code == 200
    assert new_discoveries.json() == [expected_discovery,]
    assert cloud_service_mock.return_value.send_message.assert_awaited_with(json.dumps(expected_message))

async def test_discover_paired(coordinator, paired_accessory_server, crud, get_user_bearer):
    user = await crud.create_user()
    client = TestClient(coordinator.server_service.app)
    current_discoveries = client.get('/device/discoveries', headers = get_user_bearer(user.id))
    assert current_discoveries.status_code == 200
    assert current_discoveries.json() == []

async def test_pairing(coordinator, start_accessory_server, get_user_bearer, crud):
    user = await crud.create_user()
    accessory_server = start_accessory_server()
    client = TestClient(coordinator.server_service.app)

    device_id = uuid5(UUID(int=0), '12:34:56:00:01:0A')

    device_create = {
        'name': 'Test Device 123',
        'note': 'test note',
        'icon': 'test icon',
        'category': 'test category',
        'room_id': str(uuid4()),
        'discovery_id': str(device_id),
        'credentials': '031-45-154',
    }

    r = client.post('/device', json=device_create, headers=get_user_bearer(user.id))
    assert r.status_code == 200
    assert accessory_server.is_paired

    # checking all data is passed and saved properly
    async with create_async_session() as session:
        saved_device = await session.get(Device, UUID(r.json()['id']))
    assert saved_device is not None

    # checking creation data provided by user and saved by the core
    assert device_create.items() <= saved_device.dict().items()

    # checking system data provided by integration
    assert saved_device.controller == 'homekit'
    assert saved_device.transport == 'ip'

    # checking data saved by integration manually
    assert saved_device.manufacturer == 'lusiardi.de'
    assert saved_device.integration_data['pairing_data'] == {
        'AccessoryPairingID': '12:34:56:00:01:0A',
        'AccessoryLTPK': '7986cf939de8986f428744e36ed72d86189bea46b4dcdc8d9d79a3e4fceb92b9',
        'AccessoryLTSK': '3d99f3e959a1f93af4056966f858074b2a1fdec1c5fd84a51ea96f9fa004156a',
        'iOSDeviceId': 'decc6fa3-de3e-41c9-adba-ef7409821bfc',
        'iOSDeviceLTPK': 'd708df2fbf4a8779669f0ccd43f4962d6d49e4274f88b1292f822edc3bcf8ed8',
        'iOSDeviceLTSK': 'fa45f082ef87efc6c8c8d043d74084a3ea923a2253e323a7eb9917b4090c2fcc',
        'Connection': 'IP',
        'AccessoryIP': '127.0.0.1',
        'AccessoryPort': accessory_server.data.port
    }

async def test_unpairing(coordinator, paired_accessory_server, crud, get_user_bearer):
    user = await crud.create_user()
    accessory_server, _ = paired_accessory_server
    device_id = uuid5(UUID(int=0), '12:34:56:00:01:0A')
    client = TestClient(coordinator.server_service.app)

    r = client.delete(f'/device/{device_id}', headers = get_user_bearer(user.id))
    assert r.status_code == 200

    assert not accessory_server.is_paired

    r2 = client.get(f'/device/{device_id}', headers = get_user_bearer(user.id))
    assert r2.status_code == 404

async def test_control(coordinator, paired_accessory_server, crud, get_user_bearer):
    user = await crud.create_user()
    _, pairing_data = paired_accessory_server

    key = (1, 1) # TODO
    value = random.randint(0, 100)

    device_id = uuid5(UUID(int=0), '12:34:56:00:01:0A')
    parameter_id = uuid5(device_id, f'{key[0]}.{key[1]}')

    msg_data = {
        'type': 'device_command',
        'data': {
            'device_id': str(device_id),
            'parameter_id': str(parameter_id),
            'value': value
        }
    }

    client = TestClient(coordinator.server_service.app)
    with client.websocket_connect('/ws', headers = get_user_bearer(user.id)) as ws:
        ws.send_json(msg_data)

    pairing = IpPairing(pairing_data)
    assert await pairing.get_characteristics([key,]) == {key: value}

async def test_events(coordinator, paired_accessory_server, crud, get_user_bearer):
    user = await crud.create_user()
    accessory_server, _ = paired_accessory_server

    key = (1, 1) # TODO
    value = 0 # random.randint(0, 100)

    device_id = uuid5(UUID(int=0), '12:34:56:00:01:0A')
    parameter_id = uuid5(device_id, f'{key[0]}.{key[1]}')

    expected_message = {
        'type': 'majordom_did_receive_event',
        'data': {
            'device_id': str(device_id),
            'parameter_id': str(parameter_id),
            'value': value
        }
    }

    client = TestClient(coordinator.server_service.app)
    with client.websocket_connect('/ws', headers = get_user_bearer(user.id)) as ws:
        accessory_server.write_event([key])
        data = ws.receive_json()

    assert data == expected_message
