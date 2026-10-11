# BLE protocol, JBL One ↔ BandBox Trio — findings

Independent raw-protocol notes (direct BLE sniffing + a standalone Python
control script), kept alongside the main Swift/Python controller in this
repo rather than folded into it. See `../docs/protocol.md` for this repo's
own protocol reference; this folder predates it and was cross-checked
against it (see "Header fix" below).

Based on `re/captures/bandboxtrio_01.btsnoop` (first capture, ~18s,
connection + browsing in the app). ATT decoded via tshark (see
`re/probes/parse_btsnoop.py`).

## GATT — relevant handles

- `0x0004` — standard CCCD (GATT Service Changed).
- `0x03ea` — **Write** (app → amp commands).
- `0x03ec` — **Notify** (amp → app responses/status).
- `0x03ed` — CCCD for channel 0x03ec (the app writes it to enable notify at
  connection start).

All application traffic goes over this write/notify pair — a proprietary
protocol, not standard GATT beyond the initial discovery.

## Framing

Every payload (write or notify) starts with the same header:

```
00 DD  <command:2 LE>  <packet_count:1>  <packet_index:1>  <len:2 LE>  <payload: len bytes>
```

- `00 DD` — fixed magic/preamble, present in *every* observed packet.
- `type` — seen `01`, `02`, `03`, `04` so far. Hypothesis: `01`=simple query,
  `02`=request with parameters, `03`=bulk/data response, `04`=keepalive/ack
  (payload always `00040002000000`, very high frequency, always the same).
- `seq` — a counter that seems to reset to `01` on each "conversation" (not
  yet clear whether it's per-command or per-session).
- `len` (big-endian) — length of the following payload; verified to always
  come out exact.

## Concrete findings

- **Device name/model** (notify, t≈9.85s): payload contains the ASCII
  string `"JBL BandBox Trio"` followed by `"RR0020-KP0001331"`
  (model/serial) — confirms the framing decode is correct.
- **Preset list** (large notify, t≈12.999s, two consecutive frames):
  readable ASCII strings — `Clean Comping`, `Pop Clean`, `Vintage Trem`,
  `Smooth Jazz`, `Soulful Verb`, `R&B All Night`, `Disco Twang`,
  `Funky Mouth`, `Crossroads Drive`, `Queen's Crown`, `Country Clean`,
  `Texas Boogie`, `Feathered Blues`, `Lead Solo`, `Brit Crunch`,
  `80s Arena Chorus`, `High Gain Lead`, `Coastal Drive`, `Tear Drop Verb`,
  `Voodoo Hex`, `Industrial Metal`, `US Metal`, `Acoustic`,
  `Acoustic Chorus`, `Chorus Bass`, `Studio Bass`, `Bypassed` — ~27 factory
  presets, each preceded by a growing 2-byte ID (0x0000, 0x0100, 0x0200...)
  plus one category byte.
- **Category list** (notify, t≈14.75s): `Pop`, `Funk`, `Blues`, `Rock`,
  `Metal`, `Acoustic`, `Bass`, `Others` — 8 categories with a sequential ID.
- **Control enumeration** (repeated write/notify, t≈10.5-13.2s): short
  exchanges with 2-byte IDs in a range like `0x3441`-`0x344a` — looks like
  the app querying the chain's controls/blocks one by one (EQ, effects,
  looper) to build the UI. Not yet mapped which ID corresponds to which
  function.
- **Keepalive**: `00dd04000100040002000000` on write, very high frequency
  while idle — to ignore/filter in future captures.

## Confirmed command: preset change (2 steps)

Confirmed with 2 independent captures (`bandboxtrio_01.btsnoop`, while the
user was scrolling the list and stopped on "Clean Comping";
`bandboxtrio_02_changepatch.btsnoop`, an isolated "change preset" action →
same "Clean Comping") — byte-for-byte identical sequence in both:

1. **Write `0x03ea`**, ID `0x3442` (LE `42 34`), payload `02 00 03 01`.
   The amp echoes the same sequence back as a notify on `0x03ec`
   (confirms it was applied).
2. **Write `0x03ea`**, ID `0x3443` (LE `43 34`), fixed payload `01 00 01`.
   The amp replies with a large notify: a full dump of the current preset
   (ASCII name + ~168 bytes of parameters, presumably EQ/effect values as
   floats).

Hypothesis: step 1 selects the preset, step 2 is a generic "read preset
detail" (fixed payload, not preset-specific) used to refresh the UI after
selection — so the bridge probably only needs step 1.

**Resolved by diff** (`bandboxtrio_03_popclean.btsnoop` vs
`bandboxtrio_02_changepatch.btsnoop`, same exact procedure, only a
different preset selected):

| Preset | Write 0x3442 | Write 0x3443 |
|---|---|---|
| Clean Comping | `02 00 03 01` | `01 00 01` |
| Pop Clean     | `02 00 03 02` | `01 00 02` |

Only **the last byte** changes: it's the preset index, **1-based**, over
the flat list of 27 presets (not per category). Step 2 (ID `0x3443`)
carries the same index in its last byte — looks redundant/confirmatory,
not necessary for the selection itself.

**Minimal command for the bridge** — BLE write to `0x03ea`:
```
00 DD 02 00 01 00 06 00 42 34 02 00 03 <1-based index, 1 byte>
```

**Confirmed across the whole range** (`bandboxtrio_04_bypassed.btsnoop`,
`bandboxtrio_05_studiobass.btsnoop`): Studio Bass (second-to-last in the
list, position 26) → byte `1a`; Bypassed (last, position 27) → byte `1b`.
Matches exactly the 1-based position in the flat list of 27 presets, from
start to end. **The index is confirmed to be a linear 1-based value across
the whole range** — the minimal command above is reliable for the bridge.

## Confirmed command: looper start/stop

From `bandboxtrio_06_looper.btsnoop` (isolated action, starting + stopping
the looper):

- **Looper Start**: write `0x03ea`, ID `0x3140` (LE `40 31`), payload `01 00 01`.
- **Looper Stop**: write `0x03ea`, ID `0x3140`, payload `01 00 00`.

Same scheme as the preset change (2-byte LE ID + payload), consistent with
the hypothesis that `0x34xx`/`0x31xx`/etc. are "control point" IDs for the
whole control chain (EQ, effects, looper), all written to the same handle
`0x03ea` with the same framing.

While the looper is recording/playing, the amp sends a counter in a notify
(ID `0x3142`, LE `42 31`) roughly once a second — status telemetry (loop
position), not needed to drive the amp from the bridge, only useful for
optional visual feedback.

From `bandboxtrio_08_looper_play.btsnoop`, `bandboxtrio_09_looper_pause.btsnoop`,
`bandboxtrio_07_looper_delete.btsnoop` — a **second control point for the
looper**, ID `0x3145` (LE `45 31`), different from `0x3140`:

- **Looper Play/Resume**: write `0x03ea`, ID `0x3145`, payload `01 00 03`.
- **Looper Pause**: write `0x03ea`, ID `0x3145`, payload `01 00 02`.
- **Looper Delete/Clear**: write `0x03ea`, ID `0x3140`, payload `01 00 05`
  (same ID as start/stop, different enum value — **less certain**: the
  capture shows follow-up writes to other IDs right after, so this is the
  most likely command but not isolated as cleanly as the others).

Hypothesis: `0x3140`/`0x3145` are two control points of the same looper
state machine (transport: record vs. playback), with a shared state enum
(0=idle, 1=record, 2=pause, 3=play, 5=clear — not verified in full, inferred
from observed values).

**Looper Undo** (re-captured, `bandboxtrio_10_looper_undo.btsnoop`, clean):
write `0x03ea`, ID `0x3140`, payload `01 00 04`.

Confirms the shared-enum hypothesis on ID `0x3140`:

| Action | Payload (`0x3140`) |
|---|---|
| Stop | `01 00 00` |
| Start | `01 00 01` |
| Undo | `01 00 04` |
| Delete/Clear | `01 00 05` |

## Looper command table — summary for the bridge

| Action | ID | Payload |
|---|---|---|
| Record Start | `0x3140` | `01 00 01` |
| Record Stop | `0x3140` | `01 00 00` |
| Undo | `0x3140` | `01 00 04` |
| Delete/Clear | `0x3140` | `01 00 05` |
| Play/Resume | `0x3145` | `01 00 03` |
| Pause | `0x3145` | `01 00 02` |

Full write framing: `00 DD 02 00 01 00 05 00 <ID_LE:2> <payload:3>`
(len is always `05` = 2-byte ID + 3-byte payload, for these looper commands).

## General format (confirmed on 2 commands)

```
Write 0x03ea:  00 DD 02 00 01 00 <len_BE> <ID_LE:2> <payload...>
Notify 0x03ec: 00 DD 03 00 01 00 <len_BE> 00 00 <ID_LE:2> <data...>   (echo/response)
```

`ID` looks like the "control point" (parameter/action), the payload after
the ID encodes the value (preset index, on/off state, etc.) — structure
enough to generate commands by writing [ID, value] directly without having
to rebuild the whole framing from scratch each time.

## What's missing

This capture is mostly a **connection handshake + preset browsing**, not an
isolated, targeted action. To isolate the commands useful for the bridge
(precise preset change, looper start/stop/undo, tap tempo) targeted
captures are needed: **a single action per capture**, with the time noted —
see `re/captures/CAPTURE_LOG_TEMPLATE.md`.

## Next steps

1. Dedicated capture: connect, wait for idle/keepalive to settle, then
   perform **a single** preset-change press (e.g. select a different preset
   from the list) — nothing else.
2. Repeat for: looper start, looper stop, looper undo, tap tempo.
3. Compare the `0x12`/`0x1b` frames around the noted time to isolate the
   specific command (probably `type=02` with a 2-byte ID referring to the
   chosen preset, given the ID pattern seen in the preset list).

## Header fix (from comparing against github.com/opethlike/bandbox-studio)

The header is 8 bytes little-endian: `identifier u16 (0xDD00) | command u16
| packet_count u8 | packet_index u8 | payload_length u16`. So in these
captures `type` = command (1 GET response, 2 request/write, 3 notification),
`seq` = packet_count, and the length is LE (`06 00`), not BE. The payload is
a sequence of feature records `ID u16 LE | length u16 LE | value`: e.g.
preset selection = feature `0x3442`, value `[channel=3, preset_id]`; looper
record = `0x3140` value 1 byte. This repo documents many more features
(mixer, effects, preset inventory `0x3440`).

## Direct validation from a Mac (bandbox_ctl.py)

- **BandBox Solo**: `preset 5` verified on hardware (preset changed, report
  `42 34 02 00 01 05`). The Solo has a single channel: writing channel `03`
  (as on the Trio) gets a reply with channel `01`, so the channel byte is
  accepted but remapped. It advertises as `JBL BandBox Solo`; the Trio as
  `JBL BandBox Trio`.
- Finding: the amp may not advertise its name until its Bluetooth button is
  pressed; without a name it shows up as an anonymous device (no
  manufacturer data). The control service is the same on both models.
- Trio: to be repeated with the same script.

## Hardware validation matrix (bandbox_ctl.py from a Mac)

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
