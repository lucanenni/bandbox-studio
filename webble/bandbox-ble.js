// Web Bluetooth client for the JBL BandBox Trio/Solo control service.
// Same protocol as controls.py / ../re/PROTOCOL.md, ported to JS so the
// whole GUI can run client-side with no native helper and no backend.
//
// Frame format (both write and notify):
//   00 DD <command:u16 LE> <packet_count:u8> <packet_index:u8> <len:u16 LE> <payload>
// Payload for a single-fragment write is one feature record:
//   <feature_id:u16 LE> <value bytes>
// (see docs/protocol.md and re/PROTOCOL.md for how this was derived/verified)

const SERVICE_UUID = "65786365-6c70-6f69-6e74-2e636f6d0000";
const WRITE_CHAR_UUID = "65786365-6c70-6f69-6e74-2e636f6d0002";
const NOTIFY_CHAR_UUID = "65786365-6c70-6f69-6e74-2e636f6d0001";

const LOOPER_ID = 0x3140; // record transport: start/stop/undo/delete
const LOOPER_PLAYBACK_ID = 0x3145; // play/pause

const LOOPER_COMMANDS = {
  start: [LOOPER_ID, [0x01, 0x00, 0x01]],
  stop: [LOOPER_ID, [0x01, 0x00, 0x00]],
  undo: [LOOPER_ID, [0x01, 0x00, 0x04]],
  delete: [LOOPER_ID, [0x01, 0x00, 0x05]],
  play: [LOOPER_PLAYBACK_ID, [0x01, 0x00, 0x03]],
  pause: [LOOPER_PLAYBACK_ID, [0x01, 0x00, 0x02]],
};

function buildFrame(featureId, valueBytes) {
  // command=2 (write/request), packet_count=1, packet_index=0 -- matches
  // every single-fragment write observed in captures.
  const payload = new Uint8Array(2 + valueBytes.length);
  payload[0] = featureId & 0xff;
  payload[1] = (featureId >> 8) & 0xff;
  payload.set(valueBytes, 2);

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
                            value: toHex(payload.slice(pos, pos + length)) });
    pos += length;
  }
  return result;
}

function toHex(bytes) {
  return Array.from(bytes).map(b => b.toString(16).padStart(2, "0")).join("");
}

class BandBoxBLE {
  constructor(onLog) {
    this.onLog = onLog || (() => {});
    this.device = null;
    this.writeChar = null;
  }

  get deviceName() {
    return this.device ? this.device.name : null;
  }

  async connect() {
    if (!navigator.bluetooth) {
      throw new Error("Web Bluetooth not available in this browser (needs Chrome/Edge/Opera, https or localhost)");
    }
    this.device = await navigator.bluetooth.requestDevice({
      filters: [{ namePrefix: "JBL BandBox" }, { services: [SERVICE_UUID] }],
      optionalServices: [SERVICE_UUID],
    });
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
    });

    this.onLog("connected, notifications enabled");
  }

  async writeFeature(featureId, valueBytes) {
    if (!this.writeChar) throw new Error("not connected");
    const frame = buildFrame(featureId, valueBytes);
    this.onLog(`-> write: ${toHex(frame)}`);
    // write-without-response matches the captures (opcode 0x52); fall back
    // to a confirmed write if the characteristic doesn't support it.
    if (this.writeChar.properties.writeWithoutResponse) {
      await this.writeChar.writeValueWithoutResponse(frame);
    } else {
      await this.writeChar.writeValueWithResponse(frame);
    }
  }

  async selectPreset(channel, presetId) {
    return this.writeFeature(0x3442, [channel & 0xff, presetId & 0xff]);
  }

  async looper(action) {
    const cmd = LOOPER_COMMANDS[action];
    if (!cmd) throw new Error(`unknown looper action: ${action}`);
    const [featureId, value] = cmd;
    return this.writeFeature(featureId, value);
  }
}
