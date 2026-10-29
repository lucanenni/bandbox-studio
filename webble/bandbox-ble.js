// Web Bluetooth client for the JBL BandBox Trio/Solo control service.
// Same protocol as controls.py / preset_controls.py / effect_controls.py /
// mixer_controls.py / ControlRequest.swift, ported to JS so the whole GUI
// can run client-side with no native helper and no backend.
//
// Frame format (both write and notify):
//   00 DD <command:u16 LE> <packet_count:u8> <packet_index:u8> <len:u16 LE> <payload>
//
// Two payload shapes, confirmed against ControlRequest.swift's packet():
//   command=1 (plain GET, no value):   <feature_id:u16 LE>                       (len always 2)
//   command=2 (write / parameterized read): <feature_id:u16 LE> <value_len:u16 LE> <value bytes>
// (An earlier version of this file used the command=2 shape for everything
// and omitted the value_len field, which is why preset selection didn't
// work at first -- see git history on this branch.)
//
// Effects (feature 0x3445) and mixer (0x3400/0x3401/0x3405/0x3406) need a
// read before a write (current snapshot / current channel input), exactly
// as effect_controls.py and mixer_controls.py require -- this isn't a
// transport quirk, the device only accepts a complete, matching snapshot.
// Preset save/duplicate/rename (0x3446) need the target preset to be the
// one currently selected, same precondition as controls.py's Controls class.
// NONE of this (effects/mixer/save/duplicate/rename) has been exercised on
// real hardware yet; only preset select and the looper commands have (see
// ../re/PROTOCOL.md's "Hardware validation -- webble" table).

const SERVICE_UUID = "65786365-6c70-6f69-6e74-2e636f6d0000";
const WRITE_CHAR_UUID = "65786365-6c70-6f69-6e74-2e636f6d0002";
const NOTIFY_CHAR_UUID = "65786365-6c70-6f69-6e74-2e636f6d0001";

const LOOPER_ID = 0x3140; // record transport: start/stop/undo/delete
const LOOPER_PLAYBACK_ID = 0x3145; // play/pause

// One-byte enum values (see ControlRequest.swift's switch on `feature`).
const LOOPER_COMMANDS = {
  start: [LOOPER_ID, [0x01]],
  stop: [LOOPER_ID, [0x00]],
  undo: [LOOPER_ID, [0x04]],
  delete: [LOOPER_ID, [0x05]],
  play: [LOOPER_PLAYBACK_ID, [0x03]],
  pause: [LOOPER_PLAYBACK_ID, [0x02]],
};

// Effect feature 0x3445 value_layout (effect_catalog.json "wire" block):
// channel, preset_id, change, slot_id, algorithm_id, config_id, bypass, value_count, (parameter_id, float32_le)*
const EFFECT_FEATURE = 0x3445;
const EFFECT_CHANGE = { model: null /* = current model's model_change_code */, bypass: 1, parameter: 4 };
const BYPASS_ENCODING = { active: 0, bypassed: 1, omitted: 255 };

// Tuner (features 0x3100-0x3107/0x3804), ported from onboard_controls.py and
// docs/protocol.md's "Tuner session" -- found by examining JBL One 2.1.16
// and tested on a Trio via an independent BLE bridge, not yet exercised by
// this project's own Swift/Python code or on real hardware from this repo.
// Simply writing tuner_enabled does nothing; the app first claims the tuner
// page (0x3804), reads the current instrument/mode/tuning/reference, then
// enables the tuner and streams 0x3106 measurement notifications.
const TUNER_PAGE = 1; // page_in_use's page id for "tuner" (see onboard_controls.py's PAGES)
const PAGE_STATES = { not_in_use: 0, device_in_use: 1, app_in_use: 2 };
const TUNER_MODES = { auto: 0, string_1: 1, string_2: 2, string_3: 3, string_4: 4, string_5: 5, string_6: 6 };
const TUNER_INSTRUMENTS = { guitar_3_plus_3: 0, guitar_6_in_line: 1, bass_4_string: 2, ukulele: 3 };
const TUNER_TUNINGS = {
  standard: 0, drop_d: 1, full_step_down: 2, half_step_up: 3,
  open_c: 4, open_d: 5, open_e: 6, open_f: 7, open_g: 8,
  open_a: 9, drop_c_sharp: 10, drop_c_sharp_alt_1: 11,
  drop_c: 13, drop_b: 14, drop_a: 15, dadgad: 16,
  half_step_down: 17, bass_standard: 18, bass_drop_d: 19,
  bass_drop_c: 20, bass_bead: 32, bass_full_step_down: 33,
  bass_half_step_down: 34, ukulele_standard: 25, ukulele_low_g: 26,
  ukulele_traditional: 35, ukulele_english: 36, ukulele_canadian: 28,
  ukulele_baritone: 37, ukulele_slide: 38, ukulele_slack_key: 39,
};

// Heartbeat: while the tuner page is claimed, the amp periodically notifies
// feature 0x0002 (empty value); the app answers each one with this fixed
// command=4 frame carrying feature 0x0002 and no value, or the amp leaves
// the tuner page by itself after a few seconds. Per docs/protocol.md, this
// echo was implemented but NOT confirmed on real hardware -- best effort.
const HEARTBEAT_ECHO_FRAME = new Uint8Array([0x00, 0xdd, 0x04, 0x00, 0x01, 0x00, 0x04, 0x00, 0x02, 0x00, 0x00, 0x00]);

// Preset operations (feature 0x3446), ported from preset_controls.py's
// _operation(): duplicate/save_as create a new preset (device assigns the
// ID), rename/save_user_preset mutate the existing one in place.
const PRESET_OPERATION_FEATURE = 0x3446;
const PRESET_OPERATIONS = { duplicate: 1, rename: 3, save_user_preset: 4, save_as: 9 };

function buildGetFrame(featureId) {
  const frame = new Uint8Array(10);
  frame[0] = 0x00; frame[1] = 0xdd;
  frame[2] = 0x01; frame[3] = 0x00; // command = 1 (plain GET)
  frame[4] = 0x01; frame[5] = 0x00; // packet_count=1, packet_index=0
  frame[6] = 0x02; frame[7] = 0x00; // len = 2 (just the feature id)
  frame[8] = featureId & 0xff;
  frame[9] = (featureId >> 8) & 0xff;
  return frame;
}

function buildFrame(featureId, valueBytes) {
  // command=2 (write, or a parameterized read -- same wire shape either
  // way; see ControlRequest.swift, setting_write only gates validation).
  const payload = new Uint8Array(4 + valueBytes.length);
  payload[0] = featureId & 0xff;
  payload[1] = (featureId >> 8) & 0xff;
  payload[2] = valueBytes.length & 0xff;       // value length, LE
  payload[3] = (valueBytes.length >> 8) & 0xff;
  payload.set(valueBytes, 4);

  const frame = new Uint8Array(8 + payload.length);
  frame[0] = 0x00; frame[1] = 0xdd;          // identifier 0xDD00, LE
  frame[2] = 0x02; frame[3] = 0x00;          // command = 2
  frame[4] = 0x01;                           // packet_count = 1
  frame[5] = 0x00;                           // packet_index = 0
  frame[6] = payload.length & 0xff;          // len, LE
  frame[7] = (payload.length >> 8) & 0xff;
  frame.set(payload, 8);
  return frame;
}

function decodeFrame(dataView) {
  const bytes = new Uint8Array(dataView.buffer, dataView.byteOffset, dataView.byteLength);
  if (bytes.length < 8) return { error: "truncated header", hex: toHex(bytes) };
  const identifier = bytes[0] | (bytes[1] << 8);
  const command = bytes[2] | (bytes[3] << 8);
  const count = bytes[4];
  const index = bytes[5];
  const size = bytes[6] | (bytes[7] << 8);
  const result = {
    identifier, command, count, index, size,
    forwarded: identifier === 0xdd01,
    hex: toHex(bytes),
  };
  if (count !== 1 || index !== 0) {
    result.note = "fragmented frame, not decoded further";
    return result;
  }
  const payload = bytes.slice(8);
  if (payload.length < 2) { result.note = "missing status"; return result; }
  result.status = payload[0] | (payload[1] << 8);
  result.features = [];
  let pos = 2;
  while (pos + 4 <= payload.length) {
    const featureId = payload[pos] | (payload[pos + 1] << 8);
    const length = payload[pos + 2] | (payload[pos + 3] << 8);
    pos += 4;
    if (pos + length > payload.length) break;
    result.features.push({ id: "0x" + featureId.toString(16).toUpperCase().padStart(4, "0"),
                            valueHex: toHex(payload.slice(pos, pos + length)) });
    pos += length;
  }
  return result;
}

function toHex(bytes) {
  return Array.from(bytes).map(b => b.toString(16).padStart(2, "0")).join("");
}

function hexToBytes(hex) {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.substr(i * 2, 2), 16);
  return out;
}

function readFloat32LE(bytes, offset) {
  return new DataView(bytes.buffer, bytes.byteOffset + offset, 4).getFloat32(0, true);
}

function writeFloat32LE(value) {
  const b = new Uint8Array(4);
  new DataView(b.buffer).setFloat32(0, value, true);
  return b;
}

// ---- feature-value decoders (mirror current_preset.py / onboard_controls.py) ----

function parseInventory(bytes) {
  const records = [];
  let pos = 0;
  while (pos < bytes.length) {
    const presetId = bytes[pos], genre = bytes[pos + 1], length = bytes[pos + 2];
    pos += 3;
    const name = new TextDecoder("utf-8").decode(bytes.slice(pos, pos + length));
    pos += length;
    records.push({ presetId, genre, name });
  }
  return records;
}

function parseSelection(bytes) {
  return { channel: bytes[0], presetId: bytes[1] };
}

function parsePresetInfo(bytes) {
  const presetId = bytes[0], genre = bytes[1], nameLength = bytes[2];
  let pos = 3 + nameLength;
  const name = new TextDecoder("utf-8").decode(bytes.slice(3, 3 + nameLength));
  const slotCount = bytes[pos]; pos += 1;
  const slots = [];
  for (let s = 0; s < slotCount; s++) {
    const slotId = bytes[pos], algorithmId = bytes[pos + 1], configId = bytes[pos + 2],
          bypassRaw = bytes[pos + 3], parameterCount = bytes[pos + 4];
    pos += 5;
    const parameters = [];
    for (let p = 0; p < parameterCount; p++) {
      const parameterId = bytes[pos];
      const value = readFloat32LE(bytes, pos + 1);
      parameters.push({ parameterId, value });
      pos += 5;
    }
    slots.push({ slotId, algorithmId, configId, bypassRaw, parameters });
  }
  return { presetId, genre, name, slots };
}

function parseChannelInput(bytes) {
  return { channel: bytes[0], plugged: bytes[1] !== 0, inputType: bytes[2] };
}

function parseVolume(bytes) {
  return { channel: bytes[0], inputType: bytes[1], volume: bytes[2] };
}

// 0x3106 unsolicited tuner measurement: f32 frequency (Hz) | u8 string mode |
// f32 result (amp's own -150..150 deviation scale, unit not independently
// verified) | u8 has_signal. Mirrors onboard_controls.py's decode_response.
function parseTunerMeasurement(bytes) {
  return {
    frequency: readFloat32LE(bytes, 0),
    mode: bytes[4],
    result: readFloat32LE(bytes, 5),
    hasSignal: bytes[9] !== 0,
  };
}

function parsePageInUse(bytes) {
  return { page: bytes[0], state: bytes[1] };
}

function encodePresetName(name) {
  const bytes = new TextEncoder().encode(name);
  if (bytes.length > 255) throw new Error("preset name exceeds the one-byte UTF-8 length field");
  return bytes;
}

// Mirrors preset_controls.py's _operation(): channel, op code, source_id,
// 255 (destination is device-assigned, never sent), genre (255 if omitted),
// name length, name bytes.
function buildOperationValue(action, channel, sourceId, name, genre) {
  const encoded = name == null ? new Uint8Array(0) : encodePresetName(name);
  const value = new Uint8Array(6 + encoded.length);
  value.set([channel, PRESET_OPERATIONS[action], sourceId, 255,
             genre == null ? 255 : genre, encoded.length], 0);
  value.set(encoded, 6);
  return value;
}

// Mirrors preset_controls.py's _fields(): same layout, 255 = omitted.
function parseOperationFields(bytes) {
  const nameLength = bytes[5];
  if (bytes.length !== 6 + nameLength) throw new Error("operation response length does not match its name field");
  return {
    channel: bytes[0], operation: bytes[1],
    sourceId: bytes[2] === 255 ? null : bytes[2],
    newPresetId: bytes[3] === 255 ? null : bytes[3],
    genre: bytes[4] === 255 ? null : bytes[4],
    name: new TextDecoder("utf-8").decode(bytes.slice(6, 6 + nameLength)),
  };
}

class EffectCatalog {
  constructor(data) {
    this.data = data;
    this.byModelId = new Map(data.models.map(m => [m.model_id, m]));
  }

  static async load(url = "effect_catalog.json") {
    const data = await (await fetch(url)).json();
    return new EffectCatalog(data);
  }

  modelsForSlot(slotId) {
    return this.data.models.filter(m => m.slot_id === slotId);
  }

  findModel(algorithmId, configId) {
    return this.data.models.find(m => m.algorithm_id === algorithmId && m.config_id === configId);
  }

  model(modelId) {
    const m = this.byModelId.get(modelId);
    if (!m) throw new Error(`unknown model_id: ${modelId}`);
    return m;
  }
}

class BandBoxBLE {
  constructor(onLog) {
    this.onLog = onLog || (() => {});
    this.device = null;
    this.writeChar = null;
    this.pending = []; // FIFO of {resolve, reject} for in-flight request()s
    this.onTunerMeasurement = null; // set by caller: (measurement) => {...}
  }

  get deviceName() {
    return this.device ? this.device.name : null;
  }

  // showAll bypasses the name/service filters and lists every nearby BLE
  // device instead. Needed because the Solo sometimes advertises with no
  // name and without the control service UUID in its advertisement data
  // (only exposed later via GATT), so neither filter below ever matches it
  // -- unlike BandBoxProbe.swift's CoreBluetooth path, Web Bluetooth's
  // requestDevice() chooser has no RSSI or other way to tell candidates
  // apart, so in a crowded area (neighbors' BLE devices too) this alone
  // isn't enough; see scanByRssi() below for a way to actually rank them.
  async connect(showAll = false) {
    if (!navigator.bluetooth) {
      throw new Error("Web Bluetooth not available in this browser (needs Chrome/Edge/Opera, https or localhost)");
    }
    const device = await navigator.bluetooth.requestDevice(
      showAll
        ? { acceptAllDevices: true, optionalServices: [SERVICE_UUID] }
        : {
            filters: [{ namePrefix: "JBL BandBox" }, { services: [SERVICE_UUID] }],
            optionalServices: [SERVICE_UUID],
          }
    );
    await this._connectToDevice(device);
  }

  // Scans with navigator.bluetooth.requestLEScan(), an experimental API
  // (enable chrome://flags/#enable-experimental-web-platform-features,
  // restart Chrome) that reports each advertisement's RSSI directly to the
  // page -- unlike requestDevice()'s blind native chooser. onUpdate is
  // called repeatedly with the candidate list sorted strongest-first, so
  // power-cycling the Solo and watching which entry jumps to the top (near
  // -40..-60 dBm when close) identifies it even among many neighbors'
  // devices. Returns a stop() function; call it to end the scan.
  scanByRssi(onUpdate) {
    if (!navigator.bluetooth || !navigator.bluetooth.requestLEScan) {
      throw new Error(
        "requestLEScan not supported -- enable chrome://flags/#enable-experimental-web-platform-features and restart Chrome"
      );
    }
    const seen = new Map(); // device.id -> {device, rssi, name}
    const emit = () => {
      const list = Array.from(seen.values()).sort((a, b) => b.rssi - a.rssi);
      onUpdate(list);
    };
    const onAdvertisement = (event) => {
      seen.set(event.device.id, { device: event.device, rssi: event.rssi, name: event.device.name || null });
      emit();
    };
    navigator.bluetooth.addEventListener("advertisementreceived", onAdvertisement);

    let scan = null;
    const scanning = navigator.bluetooth
      .requestLEScan({ acceptAllAdvertisements: true, keepRepeatedDevices: true })
      .then((s) => {
        scan = s;
      });

    return async () => {
      await scanning;
      if (scan) scan.stop();
      navigator.bluetooth.removeEventListener("advertisementreceived", onAdvertisement);
    };
  }

  // Connects to a BluetoothDevice obtained from scanByRssi()'s candidate list.
  async connectScanned(device) {
    await this._connectToDevice(device);
  }

  async _connectToDevice(device) {
    this.device = device;
    this.onLog(`picked device: ${this.device.name || "(unnamed)"}`);
    this.device.addEventListener("gattserverdisconnected", () => this.onLog("disconnected"));

    const server = await this.device.gatt.connect();
    const service = await server.getPrimaryService(SERVICE_UUID);
    this.writeChar = await service.getCharacteristic(WRITE_CHAR_UUID);
    const notifyChar = await service.getCharacteristic(NOTIFY_CHAR_UUID);

    await notifyChar.startNotifications();
    notifyChar.addEventListener("characteristicvaluechanged", (ev) => {
      const decoded = decodeFrame(ev.target.value);
      this.onLog(`<- notify: ${JSON.stringify(decoded)}`);
      // Streamed tuner measurements and the tuner-page heartbeat are always
      // unsolicited pushes (like looper position ticks), never a reply to a
      // pending request() -- handle them regardless of the pending queue.
      for (const feature of decoded.features || []) {
        if (feature.id === "0x3106" && this.onTunerMeasurement) {
          this.onTunerMeasurement(parseTunerMeasurement(hexToBytes(feature.valueHex)));
        } else if (feature.id === "0x0002") {
          this._echoHeartbeat();
        }
      }
      if (this.pending.length === 0) return; // unsolicited push (e.g. looper position ticks)
      const waiter = this.pending[0];
      const matches = !waiter.expectedFeatureHex ||
        (decoded.features || []).some((f) => f.id === waiter.expectedFeatureHex);
      if (!matches) return; // not the reply we're waiting for; keep waiting
      this.pending.shift();
      waiter.resolve(decoded);
    });

    this.onLog("connected, notifications enabled");
  }

  async _send(frame) {
    if (!this.writeChar) throw new Error("not connected");
    this.onLog(`-> write: ${toHex(frame)}`);
    if (this.writeChar.properties.writeWithoutResponse) {
      await this.writeChar.writeValueWithoutResponse(frame);
    } else {
      await this.writeChar.writeValueWithResponse(frame);
    }
  }

  /** Send a frame and resolve with the next notification that carries
   * expectedFeatureHex (e.g. "0x3442"), ignoring any unsolicited
   * notifications in between -- the looper pushes unprompted position/state
   * ticks (~1/s while active) that would otherwise be mistaken for the
   * reply to an unrelated request. Pass no expectedFeatureHex to accept
   * the very next notification regardless of content (legacy behavior). */
  async request(frame, expectedFeatureHex, timeoutMs = 4000) {
    const promise = new Promise((resolve, reject) => {
      const waiter = {
        resolve: (v) => { clearTimeout(timer); resolve(v); },
        reject,
        expectedFeatureHex,
      };
      const timer = setTimeout(() => {
        const idx = this.pending.indexOf(waiter);
        if (idx !== -1) this.pending.splice(idx, 1);
        reject(new Error("timed out waiting for a response"));
      }, timeoutMs);
      this.pending.push(waiter);
    });
    await this._send(frame);
    return promise;
  }

  async _echoHeartbeat() {
    try {
      await this._send(HEARTBEAT_ECHO_FRAME);
    } catch (e) {
      this.onLog(`heartbeat echo failed: ${e.message || e}`);
    }
  }

  async writeFeature(featureId, valueBytes) {
    return this._send(buildFrame(featureId, valueBytes));
  }

  // ---- preset select / looper (verified on hardware) ----

  async selectPreset(channel, presetId) {
    return this.writeFeature(0x3442, [channel & 0xff, presetId & 0xff]);
  }

  // 0x3140 is both the looper transport write and the GET for
  // looper_recording_state (0=stop/empty, 1-3=recording, 4=undo, 5=discard,
  // 6=cancel -- see onboard_controls.py's LOOPER_RECORDING).
  async looperRecordingState() {
    const resp = await this.request(buildGetFrame(0x3140), "0x3140");
    const feature = (resp.features || []).find(f => f.id === "0x3140");
    if (!feature) throw new Error("no looper_recording_state in response");
    return hexToBytes(feature.valueHex)[0];
  }

  async looper(action) {
    const cmd = LOOPER_COMMANDS[action];
    if (!cmd) throw new Error(`unknown looper action: ${action}`);
    const [featureId, value] = cmd;
    if (action === "start") {
      // "start" only begins a fresh recording when the device is actually
      // settled back to recording_state=0 -- sent too soon after delete/stop
      // (still mid-transition), the device reads it as an overdub instead
      // and nothing visibly happens. Poll briefly for the confirmed-empty
      // state first, mirroring the guard looper_controls.py applies on the
      // officially exposed path, instead of racing a bare write.
      const deadline = Date.now() + 2000;
      while (Date.now() < deadline) {
        if ((await this.looperRecordingState()) === 0) break;
        await new Promise((r) => setTimeout(r, 150));
      }
    }
    return this.writeFeature(featureId, value);
  }

  // ---- reads (not yet exercised on hardware) ----

  async getInventory() {
    const resp = await this.request(buildGetFrame(0x3440), "0x3440");
    const feature = (resp.features || []).find(f => f.id === "0x3440");
    if (!feature) throw new Error("no 0x3440 feature in response");
    return parseInventory(hexToBytes(feature.valueHex));
  }

  async getSelection(channel) {
    const resp = await this.request(buildFrame(0x3441, [channel]), "0x3442");
    const feature = (resp.features || []).find(f => f.id === "0x3442");
    if (!feature) throw new Error("no 0x3442 feature in response");
    return parseSelection(hexToBytes(feature.valueHex));
  }

  async getPresetDetail(presetId) {
    const resp = await this.request(buildFrame(0x3443, [presetId]), "0x3444");
    const feature = (resp.features || []).find(f => f.id === "0x3444");
    if (!feature) throw new Error("no 0x3444 feature in response");
    return parsePresetInfo(hexToBytes(feature.valueHex));
  }

  async getChannelInput(channel) {
    const resp = await this.request(buildFrame(0x3400, [channel]), "0x3401");
    const feature = (resp.features || []).find(f => f.id === "0x3401");
    if (!feature) throw new Error("no 0x3401 feature in response");
    return parseChannelInput(hexToBytes(feature.valueHex));
  }

  async getVolume(channel, inputType) {
    const resp = await this.request(buildFrame(0x3405, [channel, inputType]), "0x3406");
    const feature = (resp.features || []).find(f => f.id === "0x3406");
    if (!feature) throw new Error("no 0x3406 feature in response");
    return parseVolume(hexToBytes(feature.valueHex));
  }

  async getMasterVolume() {
    return this.getVolume(0, 0);
  }

  // ---- effect writes (need a slot read first -- see class docstring) ----

  /** slotSnapshot: one entry from getPresetDetail(presetId).slots. */
  async setEffectModel(catalog, channel, presetId, slotId, currentModelId, targetModelId) {
    const current = catalog.model(currentModelId);
    const target = catalog.model(targetModelId);
    if (target.slot_id !== slotId) throw new Error("model is not allowed in this slot");
    if (currentModelId === targetModelId) throw new Error("that model is already selected");
    const value = new Uint8Array([
      channel, presetId, current.model_change_code, slotId,
      target.algorithm_id, target.config_id, BYPASS_ENCODING.omitted, 0,
    ]);
    return this.writeFeature(EFFECT_FEATURE, value);
  }

  async setEffectBypass(channel, presetId, slotSnapshot, active) {
    const bypassRaw = active ? BYPASS_ENCODING.active : BYPASS_ENCODING.bypassed;
    if (slotSnapshot.bypassRaw === bypassRaw) throw new Error("already in that bypass state");
    const params = slotSnapshot.parameters;
    const value = new Uint8Array(8 + params.length * 5);
    value.set([channel, presetId, EFFECT_CHANGE.bypass, slotSnapshot.slotId,
                slotSnapshot.algorithmId, slotSnapshot.configId, bypassRaw, params.length], 0);
    let pos = 8;
    for (const p of params) {
      value[pos] = p.parameterId;
      value.set(writeFloat32LE(p.value), pos + 1);
      pos += 5;
    }
    return this.writeFeature(EFFECT_FEATURE, value);
  }

  /** uiValue is the UI-scale integer; wireMultiplier comes from the catalog
   * parameter definition (1.0 for almost everything, 0.1 for Compressor Ratio). */
  async setEffectParameter(channel, presetId, slotSnapshot, parameterId, uiValue, wireMultiplier) {
    const value = new Uint8Array(13);
    value.set([channel, presetId, EFFECT_CHANGE.parameter, slotSnapshot.slotId,
                slotSnapshot.algorithmId, slotSnapshot.configId, slotSnapshot.bypassRaw, 1], 0);
    value[8] = parameterId;
    value.set(writeFloat32LE(uiValue * wireMultiplier), 9);
    return this.writeFeature(EFFECT_FEATURE, value);
  }

  // ---- preset save/duplicate/rename (need current selection to match
  // sourceId -- same precondition as the Python controller) ----

  async presetOperation(action, channel, sourceId, name, genre) {
    const value = buildOperationValue(action, channel, sourceId, name, genre);
    const resp = await this.request(buildFrame(PRESET_OPERATION_FEATURE, value), "0x3446");
    const feature = (resp.features || []).find(f => f.id === "0x3446");
    if (!feature) throw new Error("no 0x3446 feature in response");
    return parseOperationFields(hexToBytes(feature.valueHex));
  }

  /** Duplicate the selected sourceId into a new preset; device assigns newPresetId. */
  async duplicatePreset(channel, sourceId, name, genre) {
    return this.presetOperation("duplicate", channel, sourceId, name, genre);
  }

  /** Save the current preview as a new preset, preserving sourceId. */
  async saveAsPreset(channel, sourceId, name, genre) {
    return this.presetOperation("save_as", channel, sourceId, name, genre);
  }

  /** Overwrite a USER preset (ID 51+) with the current preview. */
  async saveUserPreset(channel, presetId) {
    if (presetId < 51) throw new Error("only user presets (ID 51+) can be saved this way");
    return this.presetOperation("save_user_preset", channel, presetId, null, null);
  }

  /** Rename a USER preset (ID 51+) without changing its sound. */
  async renamePreset(channel, presetId, name) {
    if (presetId < 51) throw new Error("only user presets (ID 51+) can be renamed");
    return this.presetOperation("rename", channel, presetId, name, null);
  }

  // ---- tuner (see docs/protocol.md's "Tuner session"; not yet exercised
  // by this project's own Swift/Python code, nor on hardware from here) ----

  async _getByte(featureId, expectedHex) {
    const resp = await this.request(buildGetFrame(featureId), expectedHex);
    const feature = (resp.features || []).find(f => f.id === expectedHex);
    if (!feature) throw new Error(`no ${expectedHex} feature in response`);
    return hexToBytes(feature.valueHex)[0];
  }

  async getTunerEnabled() {
    return (await this._getByte(0x3100, "0x3100")) !== 0;
  }

  async setTunerEnabled(enabled) {
    return this.writeFeature(0x3100, [enabled ? 1 : 0]);
  }

  async getTunerMode() {
    return this._getByte(0x3101, "0x3101");
  }

  async setTunerMode(mode) {
    if (!(mode in TUNER_MODES)) throw new Error(`tuner mode must be one of: ${Object.keys(TUNER_MODES)}`);
    return this.writeFeature(0x3101, [TUNER_MODES[mode]]);
  }

  async getTunerInstrument() {
    return this._getByte(0x3102, "0x3102");
  }

  async setTunerInstrument(instrument) {
    if (!(instrument in TUNER_INSTRUMENTS)) throw new Error(`tuner instrument must be one of: ${Object.keys(TUNER_INSTRUMENTS)}`);
    return this.writeFeature(0x3102, [TUNER_INSTRUMENTS[instrument]]);
  }

  async getTunerTuning() {
    return this._getByte(0x3104, "0x3104");
  }

  async setTunerTuning(tuning) {
    if (!(tuning in TUNER_TUNINGS)) throw new Error(`tuner tuning must be one of: ${Object.keys(TUNER_TUNINGS)}`);
    return this.writeFeature(0x3104, [TUNER_TUNINGS[tuning]]);
  }

  async getTunerReferenceHz() {
    const resp = await this.request(buildGetFrame(0x3103), "0x3103");
    const feature = (resp.features || []).find(f => f.id === "0x3103");
    if (!feature) throw new Error("no 0x3103 feature in response");
    const bytes = hexToBytes(feature.valueHex);
    return (bytes[0] | (bytes[1] << 8)) / 10;
  }

  async setTunerReferenceHz(hz) {
    const raw = Math.round(hz * 10);
    if (!Number.isFinite(hz) || raw < 4200 || raw > 4600) {
      throw new Error("tuner reference must be 420.0..460.0 Hz in 0.1 Hz steps");
    }
    return this.writeFeature(0x3103, [raw & 0xff, (raw >> 8) & 0xff]);
  }

  /** Read the current instrument/mode/tuning/reference in one call, as the
   * app does before enabling the tuner (see docs/protocol.md). */
  async getTunerSettings() {
    return {
      instrument: await this.getTunerInstrument(),
      mode: await this.getTunerMode(),
      tuning: await this.getTunerTuning(),
      referenceHz: await this.getTunerReferenceHz(),
    };
  }

  async claimTunerPage() {
    return this.writeFeature(0x3804, [TUNER_PAGE, PAGE_STATES.app_in_use]);
  }

  async releaseTunerPage() {
    return this.writeFeature(0x3804, [TUNER_PAGE, PAGE_STATES.not_in_use]);
  }

  async getTunerPageInUse() {
    const resp = await this.request(buildFrame(0x3803, [TUNER_PAGE]), "0x3804");
    const feature = (resp.features || []).find(f => f.id === "0x3804");
    if (!feature) throw new Error("no 0x3804 feature in response");
    return parsePageInUse(hexToBytes(feature.valueHex));
  }

  /** Claim the tuner page and enable the tuner. Measurements then stream as
   * 0x3106 notifications to onTunerMeasurement -- set that before calling.
   * Settings default to whatever the amp already has (pass to override). */
  async startTuner({ instrument, mode, tuning, referenceHz } = {}) {
    await this.claimTunerPage();
    if (instrument != null) await this.setTunerInstrument(instrument);
    if (mode != null) await this.setTunerMode(mode);
    if (tuning != null) await this.setTunerTuning(tuning);
    if (referenceHz != null) await this.setTunerReferenceHz(referenceHz);
    await this.setTunerEnabled(true);
  }

  /** Disable the tuner and release the page. Per docs/protocol.md, skipping
   * this (or an unanswered heartbeat) makes the amp leave the page itself
   * after a few seconds anyway, but this is the clean, documented way. */
  async stopTuner() {
    await this.setTunerEnabled(false);
    await this.releaseTunerPage();
  }

  // ---- mixer writes ----

  async setMasterVolume(value) {
    return this.writeFeature(0x3406, [0, 0, value]);
  }

  async setChannelVolume(channel, inputType, value) {
    return this.writeFeature(0x3406, [channel, inputType, value]);
  }
}
