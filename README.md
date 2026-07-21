# integration-homekit

A [MajorDom](https://majordom.io) integration — bridges **Apple HomeKit** accessories into the
MajorDom language.

Built for the **MajorDom Hub**, but it doesn't need it: this is a standalone, standardized
library for HomeKit that you can use on its own (see **Run it standalone** below). Built on the
[MajorDom Integration SDK](https://github.com/MajorDom-Systems/integration-sdk). The entry point
is `HomeKitController` (`majordom_homekit/controller.py`), which the Hub — or the SDK's dev runner —
instantiates and drives through its lifecycle: discovery → pairing → commands → teardown.

- **Other protocols:** browse the [MajorDom integrations](https://github.com/orgs/MajorDom-Systems/repositories?q=integration-).
- **Create your own:** start from the [integration template](https://github.com/MajorDom-Systems/integration-template).

## Documentation

Full integration-author docs — the controller lifecycle, data models, storing data, discovery,
and a worked example — live at **[docs.majordom.io](https://docs.majordom.io/device-integration)**.

## Development

```sh
poetry install && poetry run poe install
```

| Task | Description |
|------|-------------|
| `poe check` | Full quality pipeline (ruff, ty, pytest, poetry build/check) |
| `poe check --ci` | Same, plus `git diff --exit-code` |

Work lands on `develop`; `master` is protected and released via **Actions → Release**. Tests drive
the controller with the SDK's test doubles against an in-process fake HAP accessory server — no real
accessory required (see `tests/`).

## Run it standalone (without the Hub)

`majordom-homekit` is a standalone library — import it into your own app, or run **just this
integration** interactively (discover, pair, control, and inspect devices from a prompt) with no Hub.
It discovers IP accessories over mDNS (BLE accessories need a BLE adapter); no external service is
required.

See **[Standalone mode](https://docs.majordom.io/device-integration/standalone)** for the interactive
CLI, watch mode, and the programmatic API.

## About this integration

- **Protocol / platform:** Apple HomeKit Accessory Protocol (HAP) via the
  [`parker-aiohomekit`](https://pypi.org/project/parker-aiohomekit/) fork of `aiohomekit`.
- **Transport(s):** IP (Wi-Fi / Ethernet, discovered via mDNS); BLE for BLE accessories.
- **Supported devices:** HomeKit-compatible accessories — lights, plugs, switches, sensors, locks.
- **Credentials needed to pair:** `code` (the accessory's 8-digit HomeKit setup code).

### Required harness

- **Hardware adapters:** a BLE adapter only if pairing BLE accessories; IP accessories need none.
- **Third-party software services:** none — `aiohomekit` speaks HAP directly.
- **OS / permissions:** mDNS on the LAN for discovery; BLE access for BLE accessories.

### Protocol stack (OSI)

| OSI layer | Protocol | Implemented by |
|-----------|----------|----------------|
| Application (7) | HAP characteristics / services | **this integration** (via `aiohomekit`) |
| Session (5) | Pair-Setup / Pair-Verify (SRP, Ed25519) | library (`aiohomekit`) |
| Transport (4) | TCP (IP) / GATT (BLE) | OS |
| Network + below (1–3) | IP over Wi-Fi / Ethernet (or BLE) | OS |

### Progress

- [x] Discovery services registered (mDNS via `zeroconf_discovery_service`; BLE where applicable); cancel closures called in `stop`
- [x] Discovery listeners fire and call `controller_did_receive_discovery`
- [x] Re-discovery of already-paired accessories on reconnect (`controller_did_connect_device`)
- [x] Device pairing (HAP pair-setup with the setup code)
- [x] Device schema mapped: services/characteristics → parameter list with per-parameter metadata
- [x] Hub → Device control (`send_command`)
- [x] Device → Hub event subscription (`controller_did_receive_events`)
- [x] `identify`
- [x] `unpair`
- [x] `fetch`
- [x] Availability tracking while running (`controller_did_lose_device` / `last_error`)
- [x] Graceful shutdown in `stop`
- [x] Tests pass against a fake HAP accessory server (`tests/`)

### Notes

Uses the `parker-aiohomekit` fork of `aiohomekit`; note its Python upper bound (`<3.14`).

## License

See [LICENSE](LICENSE). For commercial licensing or partnership inquiries regarding MajorDom,
contact us via [parker-industries.org/partnership](https://parker-industries.org/partnership).
