"""HomeKit integration for MajorDom.

Bridges HomeKit accessories into the MajorDom language. `peripherals` is what the Hub (or the
SDK's standalone dev runner) runs: `HomeKitController`, which needs the runtime's zeroconf.
"""

from majordom_integration_sdk import Peripheral, Platform

from majordom_homekit.controller import HomeKitController


def peripherals(platform: Platform) -> list[Peripheral]:
    return [HomeKitController(platform)]


__all__ = ["HomeKitController", "peripherals"]
