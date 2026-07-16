# end-to-end test

import asyncio
import json
import random
from uuid import UUID, uuid5

import pytest
from aiohomekit.controller.zeroconf.ip import IpPairing
from aiohomekit.model.characteristics import CharacteristicKey, CharacteristicKeyValue
from starlette.websockets import WebSocketDisconnect

from majordom_hub.models.device import Device
from majordom_hub.utils.database import create_async_session


@pytest.mark.asyncio
async def test_discover_unpaired(start_accessory_server, async_client, cloud_service_mock, crud, get_user_bearer):
    await start_accessory_server()
    user = await crud.create_user()

    discovery_id = str(UUID("70c3b8fa-709d-5e1b-8ea9-a12bb0a24fac"))
    expected_discovery = {
        "id": discovery_id,
        "integration": "HomeKit",
        "expected_credentials_options": ["code"],
        "expiration": None,
        "transport": "IP",
        # device_manufacturer='lusiardi.de',
        "device_manufacturer": None,  # it's available only after pairing
        "device_name": "Testlicht",
        "device_category": "5",  # 'Lightbulb', TODO: convert category
        "device_icon": None,
        "last_error": None,
    }
    expected_message = {"type": "majordom_did_discover_discovery", "data": expected_discovery}

    # zeroconf mock makes the discovery appear immediately, so it doesn't depend on the accessory server
    # TODO: test discovery after ws connection

    # current_discoveries = await async_client.get('/v1/api/device/discoveries', headers = get_user_bearer(user.id))
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

    new_discoveries = await async_client.get("/v1/api/device/discoveries", headers=get_user_bearer(user.id))
    assert new_discoveries.status_code == 200
    assert new_discoveries.json() == {discovery_id: expected_discovery}
    cloud_service_mock.assert_awaited()
    cloud_service_mock.assert_awaited_with(json.dumps(expected_message, separators=(",", ":")))


@pytest.mark.asyncio
async def test_discover_paired(client, paired_accessory_server, crud, get_user_bearer):
    user = await crud.create_user()
    current_discoveries = client.get("/v1/api/device/discoveries", headers=get_user_bearer(user.id))
    assert current_discoveries.status_code == 200
    assert current_discoveries.json() == {}


@pytest.mark.asyncio
async def test_pairing(start_accessory_server, async_client, get_user_bearer, crud):
    user = await crud.create_user()
    room = await crud.create_room()
    accessory_server = await start_accessory_server()

    device_id = UUID("70c3b8fa-709d-5e1b-8ea9-a12bb0a24fac")

    device_create = {
        "name": "Test Device 123",
        "note": "test note",
        "icon": "test icon",
        "category": "test category",
        "room_id": room.id.hex,
        "discovery_id": str(device_id),
        "credentials": {"type": "code", "value": "031-45-154"},
    }

    r = await async_client.post("/v1/api/device", json=device_create, headers=get_user_bearer(user.id))
    assert r.status_code == 200, r.json()
    assert accessory_server.data.is_paired

    # checking all data is passed and saved properly
    async with create_async_session() as session:
        saved_device = await session.get(Device, UUID(r.json()["id"]))
    assert saved_device is not None

    # checking creation data provided by user
    for key in {"discovery_id", "credentials"}:
        device_create.pop(key)  # remove extra
    saved_device.room_id = saved_device.room_id.hex  # adjust serialized type
    # assert device_create == saved_device.model_dump() # makes debugging easier sinc has better diff with -vv
    assert device_create.items() <= saved_device.dict().items()

    # checking data saved by the core
    assert saved_device.paired
    assert saved_device.available
    assert saved_device.last_seen

    # checking system data provided by integration
    assert saved_device.integration == "HomeKit"
    assert saved_device.transport == "IP"

    # checking data saved by integration manually
    assert saved_device.manufacturer == "lusiardi.de"
    assert saved_device.integration_data
    assert saved_device.integration_data["characteristics_cache"]
    assert saved_device.integration_data["pairing_data"]
    assert saved_device.integration_data["pairing_data"]["Connection"] == "IP"
    assert saved_device.integration_data["pairing_data"]["AccessoryPairingID"] == "12:34:56:00:01:0A"
    assert saved_device.integration_data["pairing_data"]["AccessoryLTPK"] == "7986cf939de8986f428744e36ed72d86189bea46b4dcdc8d9d79a3e4fceb92b9"
    assert saved_device.integration_data["pairing_data"]["AccessoryAddress"] == "127.0.0.1"
    # TODO: Got pairing data but not ip pairing data, need to fix
    assert saved_device.integration_data["pairing_data"]["AccessoryPort"] == accessory_server.data.port
    assert saved_device.integration_data["pairing_data"]["AccessoryIPs"] == ["127.0.0.1"]

    # test pairing data (try to connect)
    assert await IpPairing(saved_device.integration_data["pairing_data"]).get_characteristics([CharacteristicKey(1, 9)]) == {
        CharacteristicKey(1, 9): {"value": False},
    }


@pytest.mark.asyncio
async def test_unpairing(paired_accessory_server, crud, get_user_bearer, async_client):
    user = await crud.create_user()
    accessory_server, _ = paired_accessory_server
    device_id = UUID("70c3b8fa-709d-5e1b-8ea9-a12bb0a24fac")
    """
    Aiohomekit's connection is event-loop-bound. Coordinator -> aiohomekit is created in pytest's event loop, but accessed from TestClient's (?) event loop. Event loop change results in unexpected behavior and silent hangs.

    The new loop is created by sync TestClient to run an async endpoint in a background thread.

    Options:
        - (solved) swap testclient for an async test client e.g. from httpx
        - ditch testclient and really call the uvicorn server - doesn't look elegant
        - move all coordinator logic inside fastapi's lifespan - brakes app's hierarchy
    """

    r = await async_client.delete(f"/v1/api/device/{device_id}", headers=get_user_bearer(user.id))
    assert r.status_code == 200

    assert not accessory_server.data.is_paired

    r2 = await async_client.get(f"/v1/api/device/{device_id}", headers=get_user_bearer(user.id))
    assert r2.status_code == 404


@pytest.mark.asyncio
async def test_control(paired_accessory_server, async_client_ws_connect, crud, get_pairing_data):
    user = await crud.create_user()
    _, pairing_data = paired_accessory_server

    key = (1, 10)  # Brightness 1...100
    value = random.randint(0, 100)

    device_id = UUID("70c3b8fa-709d-5e1b-8ea9-a12bb0a24fac")
    parameter_id = uuid5(device_id, f"{key[0]}.{key[1]}")

    msg_data = {"type": "device_command", "data": {"device_id": str(device_id), "parameter_id": str(parameter_id), "value": value}}

    message = None
    try:
        async with async_client_ws_connect(user.id) as ws:
            # TODO: update project dependency after the fix of https://github.com/frankie567/httpx-ws/issues/97
            while True:
                await ws.send_json(msg_data)
                async with asyncio.timeout(1):
                    message = await ws.receive_json()
                if message["type"] == "majordom_did_connect_device":
                    continue  # wrong but expected msg, ignore
                else:
                    break  # might be a correct message, exit
    except WebSocketDisconnect as e:
        assert e.code == 1000

    assert message and message.get("type") == "majordom_did_receive_event", message  # make sure the message is received
    assert await IpPairing(pairing_data).get_characteristics([CharacteristicKey(*key)]) == {CharacteristicKey(*key): {"value": value}}


@pytest.mark.asyncio
async def test_events(paired_accessory_server, async_client_ws_connect, crud, get_user_bearer, get_pairing_data):
    user = await crud.create_user()
    accessory_server, _ = paired_accessory_server

    key = (1, 10)  # Brightness 1...100
    value = 0  # random.randint(0, 100)

    device_id = UUID("70c3b8fa-709d-5e1b-8ea9-a12bb0a24fac")
    parameter_id = uuid5(device_id, f"{key[0]}.{key[1]}")

    expected_message = {
        "type": "majordom_did_receive_event",
        "data": {"device_id": str(device_id), "parameter_id": str(parameter_id), "value": value},
    }

    message = None

    try:
        async with async_client_ws_connect(user.id) as ws:
            await IpPairing(get_pairing_data(accessory_server.data.port)).put_characteristics([CharacteristicKeyValue(*key, value)])
            accessory_server.write_event([key])
            while True:
                async with asyncio.timeout(1):
                    message = await ws.receive_json()
                if message["type"] == "majordom_did_connect_device":
                    continue  # ignore this message
                elif message == expected_message:
                    break  # exit
    except WebSocketDisconnect as e:
        assert e.code == 1000

    assert message == expected_message  # make sure the message is received
