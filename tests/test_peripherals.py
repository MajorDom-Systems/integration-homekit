"""What the package exports, run as the Hub runs it: under the SDK's runtime, beside its zeroconf."""

import asyncio
from collections.abc import Callable
from pathlib import Path

from conftest import PAIRING_DATA, provisional_device
from majordom_integration_sdk import Platform
from majordom_integration_sdk.capabilities import ZEROCONF
from majordom_integration_sdk.runtime import PeripheralState, Runtime, StatusKind
from majordom_integration_sdk.runtime.peripherals.providers.zeroconf import ZeroconfDiscoveryService
from majordom_integration_sdk.testing import RecordingRuntimeOutput

import majordom_homekit
from majordom_homekit import HomeKitController


async def _wait_for(predicate: Callable[[], bool], timeout: float = 2.0):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.02)


def _run_beside_zeroconf(platform: Platform, data: Path) -> tuple[Runtime, ZeroconfDiscoveryService, HomeKitController]:
    (controller,) = majordom_homekit.peripherals(platform)
    assert isinstance(controller, HomeKitController)
    zeroconf = ZeroconfDiscoveryService()
    return (
        Runtime(data, [zeroconf, controller], platform=platform, output=RecordingRuntimeOutput()),
        zeroconf,
        controller,
    )


async def test_runs_the_controller_once_zeroconf_serves(platform, tmp_path):
    runtime, zeroconf, controller = _run_beside_zeroconf(platform, tmp_path / "data")
    await runtime.start()
    try:
        await _wait_for(lambda: runtime.status(controller).state == PeripheralState.RUNNING)
        assert controller.platform is platform
        assert controller.key == "homekit"
        assert controller.peripherals.instance(ZEROCONF) is zeroconf
    finally:
        await runtime.stop()


async def test_waits_while_zeroconf_is_disabled(platform, tmp_path):
    runtime, zeroconf, controller = _run_beside_zeroconf(platform, tmp_path / "data")
    await runtime.start()
    try:
        await _wait_for(lambda: runtime.status(controller).state == PeripheralState.RUNNING)
        await runtime.disable(zeroconf)
        await _wait_for(lambda: runtime.status(controller).kind == StatusKind.NEEDS_UNBOUND)
        assert runtime.status(controller).state == PeripheralState.WAITING

        await runtime.enable(zeroconf)
        await _wait_for(lambda: runtime.status(controller).state == PeripheralState.RUNNING)
    finally:
        await runtime.stop()


async def test_starts_again_on_a_restarted_zeroconf(platform, tmp_path):
    # its AsyncZeroconf closes with it: HomeKit must browse on the new one
    runtime, zeroconf, controller = _run_beside_zeroconf(platform, tmp_path / "data")
    await runtime.start()
    try:
        await _wait_for(lambda: runtime.status(controller).state == PeripheralState.RUNNING)
        before = controller._aiohomekit

        await runtime.restart(zeroconf)
        await _wait_for(
            lambda: (
                runtime.status(controller).state == PeripheralState.RUNNING
                and controller._aiohomekit_controller not in (None, before)
            )
        )
    finally:
        await runtime.stop()


async def test_keeps_running_beside_an_accessory_that_dropped_us(unpaired_server, platform, repository, tmp_path):
    server = await unpaired_server()  # answers, but holds no pairing for us any more
    async with repository() as repo:
        await repo.save(provisional_device({**PAIRING_DATA, "AccessoryPort": server.data.port}))
    runtime, _, controller = _run_beside_zeroconf(platform, tmp_path / "data")
    await runtime.start()
    try:
        await _wait_for(lambda: runtime.status(controller).state == PeripheralState.RUNNING)
        await asyncio.sleep(0.5)  # it rediscovers the accessory, which refuses to verify the pairing
        assert runtime.status(controller).state == PeripheralState.RUNNING
    finally:
        await runtime.stop()
