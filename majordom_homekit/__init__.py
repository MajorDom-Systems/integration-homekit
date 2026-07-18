"""HomeKit integration for MajorDom.

Bridges HomeKit accessories into the MajorDom language. `HomeKitController` is the entry
point the Hub (or the SDK's standalone dev runner) instantiates and drives.
"""

from majordom_homekit.controller import HomeKitController

__all__ = ["HomeKitController"]
