# end-to-end test

import asyncio
import json
import random
from uuid import UUID, uuid5

import asyncer
import pytest
from aiohomekit.controller.zeroconf.ip import IpPairing
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from majordom_hub.models.device import Device
from majordom_hub.utils.database import create_async_session


@pytest.mark.asyncio
async def test_discover_unpaired(start_accessory_server, coordinator, cloud_service_mock, crud, get_user_bearer, client):
    await start_accessory_server()
    user = await crud.create_user()

    discovery_id = str(uuid5(UUID(int=0), '12:34:56:00:01:0A'.lower()))
    expected_discovery = {
        'id': discovery_id,
        'integration': 'HomeKit',
        'credentials': 'code',
        'expiration': None,
        'transport': 'ip',
        # device_manufacturer='lusiardi.de',
        'device_manufacturer': None, # it's available only after pairing
        'device_name': 'Testlicht',
        'device_category': '5', # 'Lightbulb', TODO: convert category
        'device_icon': None,
    }
    expected_message = {'type': 'majordom_did_discover_discovery', 'data': expected_discovery}

    # zeroconf mock makes the discovery appear immediately, so it doesn't depend on the accessory server
    # TODO: test discovery after ws connection

    # current_discoveries = client.get('/v1/api/device/discoveries', headers = get_user_bearer(user.id))
    # pprint(current_discoveries.json())
    # assert current_discoveries.status_code == 200
    # assert current_discoveries.json() == {}
    # data = None

    # try:
    #     # async with async_client.websocket_connect('/v1/ws/user', headers = get_user_bearer(user.id)) as ws:
    #     # async with aconnect_ws('/v1/ws/user', client = async_client, headers = get_user_bearer(user.id)) as ws:
    #     with client.websocket_connect('v1/ws/user/', headers = get_user_bearer(user.id)) as ws:
    #         async with asyncio.timeout(1):
    #             data = await asyncer.asyncify(ws.receive_json)()
    # except WebSocketDisconnect as e:
    #     assert e.code == 1000

    # assert data == expected_message

    new_discoveries = client.get('/v1/api/device/discoveries', headers = get_user_bearer(user.id))
    assert new_discoveries.status_code == 200
    assert new_discoveries.json() == {discovery_id: expected_discovery}
    cloud_service_mock.assert_awaited()
    cloud_service_mock.assert_awaited_with(json.dumps(expected_message, separators=(',', ':')))

@pytest.mark.asyncio
async def test_discover_paired(coordinator, paired_accessory_server, crud, get_user_bearer):
    user = await crud.create_user()
    client = TestClient(coordinator.server_service.app)
    current_discoveries = client.get('/v1/api/device/discoveries', headers = get_user_bearer(user.id))
    assert current_discoveries.status_code == 200
    assert current_discoveries.json() == {}

@pytest.mark.asyncio
async def test_pairing(start_accessory_server, coordinator, get_user_bearer, crud):
    user = await crud.create_user()
    room = await crud.create_room()
    accessory_server = await start_accessory_server()
    client = TestClient(coordinator.server_service.app)

    device_id = uuid5(UUID(int=0), '12:34:56:00:01:0A'.lower())

    device_create = {
        'name': 'Test Device 123',
        'note': 'test note',
        'icon': 'test icon',
        'category': 'test category',
        'room_id': room.id.hex,
        'discovery_id': str(device_id),
        'credentials': '031-45-154',
    }

    r = client.post('/v1/api/device', json=device_create, headers=get_user_bearer(user.id))
    assert r.status_code == 200, r.json()
    assert accessory_server.data.is_paired

    # checking all data is passed and saved properly
    async with create_async_session() as session:
        saved_device = await session.get(Device, UUID(r.json()['id']))
    assert saved_device is not None

    # checking creation data provided by user
    for key in {'discovery_id', 'credentials'}: device_create.pop(key) # remove extra
    saved_device.room_id = saved_device.room_id.hex # adjust serialized type
    # assert device_create == saved_device.dict() # makes debugging easier sinc has better diff with -vv
    assert device_create.items() <= saved_device.dict().items()

    # checking data saved by the core
    assert saved_device.paired
    assert saved_device.available
    assert saved_device.last_seen

    # checking system data provided by integration
    assert saved_device.integration == 'homekit'
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

@pytest.mark.asyncio
async def test_unpairing(paired_accessory_server, coordinator, crud, get_user_bearer):
    user = await crud.create_user()
    accessory_server, _ = paired_accessory_server
    device_id = uuid5(UUID(int=0), '12:34:56:00:01:0A'.lower())
    client = TestClient(coordinator.server_service.app)

    r = client.delete(f'/v1/api/device/{device_id}', headers = get_user_bearer(user.id))
    assert r.status_code == 200

    assert not accessory_server.data.is_paired

    r2 = client.get(f'/v1/api/device/{device_id}', headers = get_user_bearer(user.id))
    assert r2.status_code == 404

@pytest.mark.asyncio
async def test_control(paired_accessory_server, coordinator, crud, get_user_bearer):
    user = await crud.create_user()
    _, pairing_data = paired_accessory_server

    key = (1, 1) # TODO
    value = random.randint(0, 100)

    device_id = uuid5(UUID(int=0), '12:34:56:00:01:0A'.lower())
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
    try:
        with client.websocket_connect('/v1/ws/user', headers = get_user_bearer(user.id)) as ws:
            ws.send_json(msg_data)
    except WebSocketDisconnect as e:
        assert e.code == 1000

    pairing = IpPairing(pairing_data)
    assert await pairing.get_characteristics([key,]) == {key: value}

@pytest.mark.asyncio
async def test_events(paired_accessory_server,coordinator, crud, get_user_bearer):
    user = await crud.create_user()
    accessory_server, _ = paired_accessory_server

    key = (1, 1) # TODO
    value = 0 # random.randint(0, 100)
    # TODO: write value to key before writinge event?

    device_id = uuid5(UUID(int=0), '12:34:56:00:01:0A'.lower())
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
    data = None

    try:
        with client.websocket_connect('/v1/ws/user', headers = get_user_bearer(user.id)) as ws:
            accessory_server.write_event([key])
            async with asyncio.timeout(1):
                data = await asyncer.asyncify(ws.receive_json)()
    except WebSocketDisconnect as e:
            assert e.code == 1000

    assert data == expected_message
