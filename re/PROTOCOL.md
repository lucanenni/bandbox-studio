# BLE protocol, JBL One ↔ BandBox Trio — findings

Independent raw-protocol notes (direct BLE sniffing + a standalone Python
control script), kept alongside the main Swift/Python controller in this
repo rather than folded into it. See `../docs/protocol.md` for this repo's
clean protocol reference (feature-ID table, values, saved/live-edit
semantics); this doc instead covers what that one doesn't: raw ATT handles
(for implementers not going through CoreBluetooth, e.g. Web Bluetooth or
`bleak`), the byte-level sniffing process, and the looper's exact wire
bytes.

Findings below come from a series of targeted BLE captures (PacketLogger,
iPhone + Mac, one action per capture — see `BLE_SNIFFING_SETUP.md` and
`captures/CAPTURE_LOG_TEMPLATE.md`). The raw captures aren't kept in this
repo, since they embed real device MAC addresses and the amp's serial
number; only the findings distilled below survive.

## GATT — relevant handles

- `0x0004` — standard CCCD (GATT Service Changed).
- `0x03ea` — **Write** (app → amp commands).
- `0x03ec` — **Notify** (amp → app responses/status).
- `0x03ed` — CCCD for channel 0x03ec (the app writes it to enable notify at
  connection start).

All application traffic goes over this write/notify pair — a proprietary
protocol, not standard GATT beyond the initial discovery.

## Framing

Every payload (write or notify) starts with the same 8-byte little-endian
header, matching `docs/protocol.md`'s "Frames and responses":

```
identifier:u16 (0xDD00) | command:u16 | packet_count:u8 | packet_index:u8 | payload_length:u16
```

`command` = 1 (GET response), 2 (request: write or parameterized read), or
3 (notification); `0xDD01` as the identifier indicates forwarding. The
payload is a sequence of feature records: `ID:u16 LE | length:u16 LE |
value`, e.g. preset selection is feature `0x3442` with value
`[channel, preset_id]`, looper record is `0x3140` with a 1-byte value. See
`docs/protocol.md`'s feature table for the full set this repo implements;
the sections below give the exact looper bytes, which aren't spelled out
there.

A high-frequency keepalive (`00dd04000100040002000000` on write) appears
constantly while idle — safe to ignore/filter in captures.

## Concrete findings (first capture)

- **Device name/model** (notify): payload contains the ASCII string
  `"JBL BandBox Trio"` followed by a model/serial string (format
  `RR0020-KPxxxxxxx`) — confirms the framing decode is correct.
- **Preset list** (large notify, two consecutive frames): readable ASCII
  strings — `Clean Comping`, `Pop Clean`, `Vintage Trem`, `Smooth Jazz`,
  `Soulful Verb`, `R&B All Night`, `Disco Twang`, `Funky Mouth`,
  `Crossroads Drive`, `Queen's Crown`, `Country Clean`, `Texas Boogie`,
  `Feathered Blues`, `Lead Solo`, `Brit Crunch`, `80s Arena Chorus`,
  `High Gain Lead`, `Coastal Drive`, `Tear Drop Verb`, `Voodoo Hex`,
  `Industrial Metal`, `US Metal`, `Acoustic`, `Acoustic Chorus`,
  `Chorus Bass`, `Studio Bass`, `Bypassed` — ~27 factory presets, each
  preceded by a growing 2-byte ID (0x0000, 0x0100, 0x0200...) plus one
  category byte.
- **Category list** (notify): `Pop`, `Funk`, `Blues`, `Rock`, `Metal`,
  `Acoustic`, `Bass`, `Others` — 8 categories with a sequential ID.
- **Control enumeration** (repeated write/notify): short exchanges with
  2-byte IDs in a range like `0x3441`-`0x344a` — the app querying the
  chain's controls/blocks one by one (EQ, effects, looper) to build the UI.

## Confirmed command: preset change

Confirmed across a full range of targeted single-action captures, by diff:

| Preset | Write 0x3442 | Write 0x3443 |
|---|---|---|
| Clean Comping (1st) | `02 00 03 01` | `01 00 01` |
| Pop Clean (2nd)     | `02 00 03 02` | `01 00 02` |
| Studio Bass (26th)  | `02 00 03 1a` | — |
| Bypassed (27th/last) | `02 00 03 1b` | — |

Only **the last byte** of the `0x3442` write changes: it's the preset
index, **1-based**, linear over the flat list of 27 presets (not per
category), confirmed across the whole range from start to end. `0x3443`
(fixed payload `01 00 01`/`01 00 02`, same index in its last byte) triggers
a full preset-detail readback — redundant for selection itself, used by
the app to refresh its UI.

**Minimal command for the bridge** — BLE write to `0x03ea`:
```
00 DD 02 00 01 00 06 00 42 34 02 00 03 <1-based index, 1 byte>
```

## Confirmed command: looper

Two control points, both written to `0x03ea`:

| Action | ID | Payload |
|---|---|---|
| Record Start | `0x3140` | `01 00 01` |
| Record Stop | `0x3140` | `01 00 00` |
| Undo | `0x3140` | `01 00 04` |
| Delete/Clear | `0x3140` | `01 00 05` |
| Play/Resume | `0x3145` | `01 00 03` |
| Pause | `0x3145` | `01 00 02` |

Full write framing: `00 DD 02 00 01 00 05 00 <ID_LE:2> <payload:3>` (len is
always `05` = 2-byte ID + 3-byte payload, for these looper commands).
`0x3140` and `0x3145` are two control points of the same looper state
machine (transport: record vs. playback); both can also be read, see the
next section.

### Looper state machine (read side, hardware-tested on a Solo via bandbox-midi-bridge)

Reading a feature (`00 DD 01 00 01 00 04 00 <ID_LE:2> 00 00`, or the bridge's
`readFeature`) returns a c1 reply `status:2 feature:2 vlen:2 value`. Values:

| Feature | Meaning | Values |
|---|---|---|
| `0x3140` | recording state (also the write point) | 0 stopped/empty, 1/2/3 recording first/second/third layer, 4 undo, 5 discard, 6 cancel |
| `0x3145` | playback | 0 stop, 1 play, 2 pause, 3 resume |
| `0x3143` | recorded length | u16 LE, **not ms** (3214 for a ~9.6 s loop, 500 for ~12 s) |
| `0x3146` | position in the loop | u16 LE, same units as `0x3143`, not time; wraps to 0 each loop |
| `0x3148` | layer count | u8 (0 = empty) |
| `0x3141` | signal interval | u16, unit not verified |
| `0x3147` | bars | u8 (drum/metronome-backed loops) |
| `0x314A` | estimated duration | u32; read 1333 across different loops, meaning unknown |

Observed behavior:
- The state returns by itself: after a rec press with a loop already present
  (overdub), `0x3140` reads 1 and, at the end of the phrase, goes back to 0
  with no command sent. The first take is closed by an explicit stop; the amp
  then starts playing (`0x3145` = 1).
- `0x3140` changes are **not** notified spontaneously; poll it (the bridge
  polls one feature per 120 ms, the position every other tick).
- A write is acked with `c2 0000`. A pause/play is also echoed as c3 on
  `0x3145`.
- Spontaneous notifications while recording/playing: `0x3143` (length) and
  `0x3146` (position, mostly seen as 0 around the wrap), and `0x3142` (4-byte
  float, not loop position: values vary irregularly, about 10 per phrase;
  probably a signal level, meaning not verified). Earlier text here called
  `0x3142` a loop-position counter; that is not supported by the capture.
- The Solo reads a rec command sent too soon after stop/clear as an overdub
  (see webble's guard).
- Read replies of polled features arrive in bursts (BLE), so timing them is
  unreliable. The amp pushes a c3 notification `0x3146 = 0` at every loop wrap:
  the time between two of them is the real loop duration (confirmed on
  hardware, the bridge's progress bar uses it).
- `0x3141` and `0x3149` gave no reply on the Solo.

## Direct validation from a Mac (`../tools/bandbox_ctl.py`)

- **BandBox Solo**: `preset 5` verified on hardware (preset changed,
  report `42 34 02 00 01 05`). The Solo has a single channel: writing
  channel `03` (as on the Trio) gets a reply with channel `01`, so the
  channel byte is accepted but remapped. It advertises as
  `JBL BandBox Solo`; the Trio as `JBL BandBox Trio`. The amp may not
  advertise its name until its Bluetooth button is pressed; without a
  name it shows up as an anonymous device (no manufacturer data). The
  control service is the same on both models.

| Command | Trio | Solo |
|---|---|---|
| preset N | OK | OK |
| looper start/stop | OK (loop recorded ~42 s) | to do |
| looper delete | OK | to do |
| looper pause/play/undo | to do | to do |

## Hardware validation — webble (Web Bluetooth, Trio)

Confirmed via the `webble/` client (branch `web-bluetooth`), live on real
hardware:

| Command | Result |
|---|---|
| preset select | OK |
| looper start | OK — begins recording |
| looper stop | OK — ends recording, **playback starts immediately** (normal looper-pedal behavior, not a bug) |
| looper pause | OK — stops playback |
| looper play/resume | OK — resumes playback |
| looper delete/clear | OK — clears the loop |
| looper undo | sent, effect on the amp not confirmed yet |
