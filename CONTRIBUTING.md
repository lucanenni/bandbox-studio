# Contributing

Contributions that make the existing controls clearer, safer, or easier to verify are welcome. Keep changes small and describe the problem, resulting behavior, and validation. For a new protocol feature or a broad redesign, open an issue first so the intended scope is clear.

## Local setup and tests

Follow [the setup instructions](README.md#setup). The installer builds locally and does not touch the amp. From the repository root:

```sh
.venv/bin/python -m unittest discover -v
.venv/bin/python check_mcp.py
```

These commands use offline fixtures. `check_mcp.py` starts a local stdio server and checks its handshake and catalogs; live options are separate and opt-in.

Run the Swift Drive state-machine tests without Bluetooth access:

```sh
mkdir -p .build
cat DriveRoundTrip.swift tests/DriveRoundTripTests.swift > .build/DriveTests.swift
xcrun swiftc -parse-as-library .build/DriveTests.swift -o .build/drive-tests
.build/drive-tests
```

Rebuild the native transport after Swift changes with `./build.sh`. Restart any GUI or MCP process that was running the old version. After GUI changes, inspect the page at desktop and narrow widths, check browser errors, and exercise write flows with a simulated controller before touching hardware.

## Project layout

| Files | Responsibility |
| --- | --- |
| `BandBoxProbe.swift`, `ControlRequest.swift`, `DriveRoundTrip.swift` | macOS Bluetooth transport, native request validation, guarded Drive operation |
| `protocol.py`, `exchange_protocol.py`, `current_*.py`, `guitar_protocol.py` | Frame and response decoding |
| `preset_controls.py`, `effect_controls.py`, `onboard_controls.py`, `mixer_controls.py`, `looper_controls.py` | Named requests, ranges, and reply matching |
| `controls.py`, `drive_control.py` | Operation coordination, preview state, and cross-process guards |
| `server.py` | Local stdio MCP tools |
| `gui_server.py`, `gui/` | Loopback HTTP API and browser interface |
| `runtime_config.py`, `install.py`, `gui_launch.py` | Portable setup, runtime configuration, and launch |

## Protocol changes

Keep protocol research and hardware validation separate. Document the source of each feature ID, field, range, or enum; do not infer a BandBox command from another JBL product's behavior alone. Use synthetic fixtures and add meaningful checks for malformed replies, mismatched identity, and uncertain outcomes.

Preserve these boundaries:

- No setting writes on startup, page load, catalog access, or ordinary reads.
- No automatic write retries or automatic rollback after an uncertain result.
- No use of saved preset details as proof of unsaved live settings.
- No firmware, reset, deletion, raw-write, or loop-discard paths.
- No loss of existing loops when testing recording controls.
- Matching response content is required; an acknowledgement alone is insufficient.
- GUI and MCP mutations must share the same lease and preview-invalidation mechanism.

If hardware testing is needed, describe the exact starting state, one bounded change, the device's reply, and how the final state was checked. Test only a device you are authorized to control. Do not describe an implemented path as hardware-tested unless it was exercised.

## Issues and pull requests

For a bug report, include your commit or version, macOS and Python versions, BandBox model and firmware if known, the exact action, and expected versus actual behavior. State whether the issue occurred with the GUI, MCP, or command-line reads.

Redact peripheral UUIDs, Bluetooth addresses, personal paths, usernames, and private preset names. Do not upload APKs, firmware, decompiled vendor code, or unreviewed captures. For security-sensitive findings, follow [SECURITY.md](SECURITY.md).

Before opening a pull request, run the relevant offline checks, inspect the staged diff for generated files or personal data, and summarize any hardware validation separately. Submit only work you have the right to contribute under the project's [MIT license](LICENSE).
