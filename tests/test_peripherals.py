"""What the package exports, run as the Hub runs it: under the SDK's runtime, beside its zeroconf."""

import asyncio

from majordom_integration_sdk.runtime import PeripheralState, Runtime
from majordom_integration_sdk.runtime.peripherals.providers.zeroconf import ZeroconfDiscoveryService
from majordom_integration_sdk.testing import RecordingRuntimeOutput, build_test_platform

import majordom_homekit
from majordom_homekit import HomeKitController


async def test_runs_the_controller_once_zeroconf_serves(tmp_path):
    platform = build_test_platform(tmp_path)
    (controller,) = majordom_homekit.peripherals(platform)
    zeroconf = ZeroconfDiscoveryService()
    runtime = Runtime(tmp_path / "data", [zeroconf, controller], platform=platform, output=RecordingRuntimeOutput())

    await runtime.start()
    try:
        async with asyncio.timeout(2):
            while runtime.status(controller).state != PeripheralState.RUNNING:
                await asyncio.sleep(0.02)
        assert isinstance(controller, HomeKitController) and controller.platform is platform
        assert controller.key == "homekit"
        assert controller.peripherals.instance("mdns") is zeroconf
    finally:
        await runtime.stop()
