# HomeKit integration

Bridges the Hub to HomeKit (HAP) accessories over IP, built on top of
[`aiohomekit`](https://github.com/Jc2k/aiohomekit). `aiohomekit` owns the HAP protocol,
discovery, pairing crypto, and the live connection; this integration adapts it to the
Hub's `AbstractController` contract and persists HomeKit state in the Hub's database.

## Files

| File | Responsibility |
|---|---|
| `controller.py` | `AbstractController` implementation — lifecycle, pairing, control, and the aiohomekit discovery/event delegates |
| `mapper.py` | HAP ↔ MajorDom conversions: UUIDs (via the framework helpers), characteristic → parameter, formats/units/permissions/valid-values |
| `models.py` | Typed `integration_data` schemas (`HKDevice`, `HKParameter`, …) |
| `characteristics_storage.py` | Adapts aiohomekit's characteristics cache onto the Hub's `DeviceRepository` |
| `pairings_storage.py` | Adapts aiohomekit's pairing-data storage onto the Hub's `DeviceRepository` |

The two storage classes implement aiohomekit's storage protocols so that all HomeKit
state lives in the Hub DB rather than aiohomekit's own files. They share the controller's
single `HKMajorDomMapper` instance, so every HAP id maps to the same MajorDom UUID
everywhere.

## Discovery & pairing

- **Discovery** uses the Hub's shared Zeroconf service: aiohomekit browses `_hap._tcp` /
  `_hap._udp` using the `AsyncZeroconf` handed to it from
  `dependencies.zeroconf_discovery_service`, and calls back into
  `_aiohomekit_did_discover`. Already-paired accessories seen again trigger a reconnect;
  accessories paired to another controller are surfaced but not offered for pairing.
- **Pairing** takes a HAP setup code (`CredentialsType.code`, `DDD-DD-DDD`). The credentials
  type is validated against the discovery's `expected_credentials_options` before pairing.

## Availability

aiohomekit only pushes a *became-available* signal, never *became-unavailable*, so the
controller polls each paired accessory's connection state (`_availability_loop`) and
funnels both directions through `_set_availability`, which dedupes and emits the
framework's `controller_did_connect_device` / `controller_did_lose_device`.

## Tests

`tests/test_controllers/test_homekit/` runs against aiohomekit's in-process
`AccessoryServer` (a fake accessory) — no real hardware needed.

## Not yet implemented

- BLE discovery/pairing (aiohomekit supports it; the Hub wires IP only for now).
- Multi-accessory bridges save only the first accessory's manufacturer.
