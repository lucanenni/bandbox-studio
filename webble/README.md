# webble — Web Bluetooth proof of concept

Experiment (branch `web-bluetooth`): can the whole control panel run
client-side, with no Swift helper and no backend process, using the Web
Bluetooth API?

**Scope of this PoC**: connect, preset select (channel 3, 27 factory
presets), and the full looper command set — the subset already verified on
real hardware in `../re/PROTOCOL.md`. Everything else in `controls.py`
(effects, mixer, save/duplicate/rename) is not ported yet; see
`../README.md`'s validation status for what's hardware-confirmed to port
next.

**Status: confirmed working end-to-end on real hardware** (Chrome,
`navigator.bluetooth`, no backend) — preset select, and looper
start/stop/pause/play/delete all confirmed on the Trio; see
`../re/PROTOCOL.md`'s "Hardware validation — webble" table. `undo` was sent
but its effect on the amp hasn't been confirmed yet.

## Run it

Needs **Chrome, Edge, or Opera** — Safari and every iOS browser do not
implement Web Bluetooth at all (Apple has no plans to). Needs a secure
context: serve over `http://localhost`, not `file://`.

```bash
cd webble
python3 -m http.server 8765
```

Open `http://localhost:8765` in Chrome/Edge, click **Connect to BandBox**,
pick the amp from the browser's device picker (it must already be
discoverable — if it doesn't show up, press the amp's Bluetooth button
once first; see `../re/BLE_SNIFFING_SETUP.md` for background on this).

## Files

- `index.html` — UI.
- `bandbox-ble.js` — the actual Web Bluetooth client: GATT connect, frame
  building/decoding (same wire format as `protocol.py`/`preset_controls.py`/
  `looper_controls.py`), preset select, looper commands.

## If this works out

The plan for feature parity with the native GUI:

1. Port the rest of `controls.py`'s request builders (effects, mixer,
   save/duplicate/rename) to this same JS client.
2. Decide whether `gui_server.py` stays as a plain static file server (it
   would no longer need to talk to any Swift helper — just serve
   `gui/index.html` and friends) or whether the static files move here and
   the Starlette backend goes away entirely for the GUI.
3. The **MCP server** is a separate concern: it runs as a local process via
   stdio, not in a browser, so Web Bluetooth doesn't help it. Making it
   cross-platform too would mean swapping the Swift helper for `bleak`
   (already proven to work against this exact device in
   `../re/probes/bandbox_ctl.py`) on the MCP side specifically.
