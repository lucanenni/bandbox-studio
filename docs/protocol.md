# Protocol notes

These notes describe what this implementation understands about the JBL BandBox Trio. They are an interoperability reference, not an official specification. Hardware observations come from one Trio; other models and firmware may differ. See [validation status](../README.md#validation-status) and [sources](../THIRD_PARTY_NOTICES.md).

## Transport

The native Swift helper uses macOS CoreBluetooth to discover and connect to the control service:

| Role | UUID |
| --- | --- |
| Service | `65786365-6C70-6F69-6E74-2E636F6D0000` |
| RX notifications | `65786365-6C70-6F69-6E74-2E636F6D0001` |
| TX writes | `65786365-6C70-6F69-6E74-2E636F6D0002` |

These are protocol constants, not a particular user's device identifiers. CoreBluetooth peripheral identifiers are machine-local and may change. The helper verifies the service during discovery. A failed read can rediscover a device; setting writes are never automatically repeated.

No USB transport is implemented. Bluetooth audio pairing and the BLE control connection are separate concerns. An Android phone is not required.

## Frames and responses

Protocol 4 uses an eight-byte little-endian header:

```text
identifier:u16 | command:u16 | packet_count:u8 | packet_index:u8 | payload_length:u16
```

The ordinary identifier is `0xDD00`; `0xDD01` indicates forwarding. Replies are validated for framing, status, fragmentation, and feature content. Feature records use a two-byte ID, two-byte length, and value bytes. The decoders reject incomplete or contradictory data instead of guessing.

Command `1` carries GET responses, command `2` carries requests that include both writes and parameterized semantic reads, and command `3` carries notifications. A command number by itself does not establish that a setting changed. An acknowledgement or unsolicited notification alone is not a verified value readback.

## Implemented feature families

| Features | Meaning |
| --- | --- |
| `0x3440` | Preset inventory |
| `0x3441` / `0x3442` | Current selection query / selection report and selection change |
| `0x3443` / `0x3444` | Saved preset detail query / response |
| `0x3445` | Effect model, parameter, and active/bypass changes |
| `0x3446` | User-preset operations |
| `0x3400` / `0x3401` | Channel input query / response |
| `0x3405` / `0x3406` | Mixer level query / response and change |
| `0x300x`, `0x304x`, `0x310x`, `0x314x` | Drum, metronome, tuner, and looper families; only named controls are exposed |
| `0x000D` | Raw status mapped to battery in JBL One; not independently compared to a battery display |

`onboard_controls.py` defines the actual supported subsets, ranges, and reply decoders. `effect_catalog.json` defines 44 models and their UI parameter ranges. `ControlRequest.swift` provides a separate native request allowlist.

## Values and identity

- The guitar path implemented here is channel 3, with eight blocks: GAT, COM, WAH, AMP, CAB, MOD, DLY, RVB.
- The GUI's display number is its one-based position in the returned inventory. It is not necessarily the device's internal `preset_id`. MCP calls use internal IDs returned by reads; callers must not infer an ID from the screen number.
- Model identity combines algorithm and configuration IDs. Effect parameters use the amp's UI scale. Compressor Ratio has a wire multiplier of `0.1`; a UI value of 10 is encoded as 1.
- Mixer levels are raw integers `0..32`. The master tuple is channel/input `0,0`. Channel writes require a fresh matching input report and a plugged-in input. Mixer levels are distinct from the AMP block's `0..100` Volume parameter and other JBL products' volume features.

## Saved values and live edits

A saved-detail query does **not** provide a complete snapshot of unsaved live edits. The controller establishes an editable baseline by explicitly loading a saved preset, or through a supported confirmation path in MCP. It retains verified edits to that baseline.

GUI and MCP operations use a process lock and a shared device lease. A shared revision marker invalidates another local controller's old preview after a write. Physical knob changes or changes from JBL One do not update that marker, so the user must re-establish the baseline after editing elsewhere.

Mutations need matching device reports. An uncertain outcome is exposed to the caller, invalidates the preview, and is not followed by an automatic retry or compensating write. Saving checks the stored preset content. Factory presets cannot be overwritten through the exposed save operation.

The looper adds state guards before recording or bar changes. Existing-loop overdubbing and discard are not offered. Firmware, reset, deletion, and arbitrary raw-write APIs are absent.
