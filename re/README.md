# re/ — independent BLE findings (Trio + Solo)

This folder is a separate, standalone set of BLE protocol notes and a
direct-control Python script, originally from an independent project aimed
at driving BandBox functions (preset change, looper, tap tempo, etc.) from
an **MVave Chocolate Plus** pedal through a hardware bridge (same idea as
an earlier Spark GO bridge), bypassing the JBL One app entirely.

It's kept here, alongside the main Swift/Python controller in this repo,
rather than merged into it, because it documents the raw protocol from
scratch (sniffing method, byte-level framing) and includes a **BandBox
Solo** confirmation that the rest of this repo doesn't have — see
`../docs/protocol.md#bandbox-solo` and `PROTOCOL.md`'s hardware validation
matrix.

## Layout

- `BLE_SNIFFING_SETUP.md` — how to capture BLE traffic between JBL One and
  the amp (iPhone + PacketLogger over USB).
- `PROTOCOL.md` — the protocol findings themselves (preset select, looper
  start/stop/undo/delete/play/pause), including the Solo validation matrix.
- `captures/` — `CAPTURE_LOG_TEMPLATE.md` used while sniffing. Raw capture
  files aren't kept here: they embed real BLE MAC addresses and the amp's
  serial number, and everything useful from them is already distilled into
  `PROTOCOL.md`.
- `probes/parse_btsnoop.py` — decodes a capture's ATT frames via tshark.
- `probes/bandbox_ctl.py` — talks directly to the amp over BLE from a Mac
  (via `bleak`), bypassing JBL One entirely; used to validate commands on
  real hardware (both Trio and Solo).

## Why a bridge at all

- The **MVave Chocolate Plus** speaks standard BLE-MIDI.
- The **BandBox Trio/Solo** only accepts control through the **JBL One**
  app, over a **proprietary** BLE protocol (not MIDI). No footswitch jack,
  no MIDI/BLE footswitch support documented in JBL's manual.
- Unlike the Spark GO (Positive Grid's protocol was already
  reverse-engineered publicly), there was no public reverse-engineering of
  the BandBox Trio when this started — hence this folder, and later this
  fork's own `controls.py`/`DriveRoundTrip.swift`.
