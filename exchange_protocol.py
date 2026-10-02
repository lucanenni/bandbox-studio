"""Strict, pure framing/correlation for one native --control-plan exchange.

This layer verifies framing and event order, not feature semantics or freshness
across connections. Callers must match domain values and independently read back
persistent changes. A protocol ACK is not a value or proof of persistence.
"""
import struct
from collections.abc import Mapping

from protocol import decode_frame

RX = "65786365-6C70-6F69-6E74-2E636F6D0001"
MAX_FRAGMENTS = 32
MAX_PAYLOAD = 8192


def _integer(value, minimum, maximum, label):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be an integer in {minimum}..{maximum}")
    return value


def _hex(value):
    if not isinstance(value, str):
        raise ValueError("packet/value hex must be a string")
    try:
        return bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError("invalid packet/value hexadecimal") from exc


def packet_for(request: Mapping) -> bytes:
    """Build a single direct GET or SET packet from a named builder descriptor.

    This validates representation only; the caller must supply a descriptor
    produced by an allowlisted domain builder, never a user-supplied raw feature.
    """
    if not isinstance(request, Mapping):
        raise ValueError("request must be a command descriptor")
    if not isinstance(request.get("action"), str) or not request["action"].strip():
        raise ValueError("request action must be a nonblank string")
    command = _integer(request.get("command"), 1, 2, "command")
    feature = _integer(request.get("feature"), 0, 65535, "feature")
    _integer(request.get("response_feature"), 0, 65535, "response_feature")
    if type(request.get("setting_write")) is not bool:
        raise ValueError("setting_write must be a boolean")
    value = _hex(request.get("value_hex"))
    if command == 1:
        if value or request["setting_write"]:
            raise ValueError("generic GET cannot contain a value or setting write")
        payload = struct.pack("<H", feature)
    else:
        if len(value) > MAX_PAYLOAD - 4:
            raise ValueError("request exceeds the bounded payload size")
        payload = struct.pack("<HH", feature, len(value)) + value
    return struct.pack("<HHBBH", 0xDD00, command, 1, 0, len(payload)) + payload


def parse_exchange(events: list[dict], request: Mapping) -> dict:
    """Correlate exactly one logged send with direct protocol replies.

    A malformed/ambiguous exchange clears acknowledged/feature_values. `sent`
    records whether the expected dispatch was seen; `setting_writes` records
    attempted writes even on transport failure, or None if logs contradict or
    cannot establish the count. It does not assert that hardware applied them.
    """
    expected_packet = packet_for(request)
    if not isinstance(events, list):
        raise ValueError("events must be a list")
    result = {"sent": False, "acknowledged": False, "feature_values": [],
              "errors": [], "setting_writes": 0, "connected": False}
    sends = 0
    completions = 0
    connections = 0
    writes = 0
    count_known = True
    disconnected = False
    pending = None

    def error(message, event=None):
        item = {"error": message}
        if event is not None and "time" in event:
            item["time"] = event["time"]
        result["errors"].append(item)

    def payload_result(command, payload):
        if command == 2:
            if payload != b"\x00\x00":
                raise ValueError("protocol ACK must contain exactly zero status and no values")
            result["acknowledged"] = True
            return
        combined = struct.pack("<HHBBH", 0xDD00, command, 1, 0, len(payload)) + payload
        frame = decode_frame(combined)
        if frame.get("status") != 0:
            raise ValueError("device returned nonzero response status")
        result["feature_values"].extend(
            {"feature": int(item["id"], 16), "value_hex": item["value_hex"]}
            for item in frame["features"])

    for event in events:
        if not isinstance(event, Mapping):
            count_known = False
            error("malformed event; write count cannot be established")
            continue
        kind = event.get("event")
        if not isinstance(kind, str) or not kind:
            count_known = False
            error("event lacks a valid event type; write count cannot be established", event)
            continue
        if kind == "connected":
            connections += 1
            result["connected"] = True
            if connections > 1 or completions or disconnected:
                error("another connection appeared in a single-connection exchange", event)
            continue
        if kind == "control_send":
            sends += 1
            flag = event.get("setting_write")
            try:
                raw = _hex(event.get("hex"))
                if len(raw) < 8 or len(raw) != 8 + struct.unpack_from("<H", raw, 6)[0]:
                    raise ValueError("logged send has invalid packet length")
            except ValueError as exc:
                raw = None
                count_known = False
                error(str(exc), event)
            if type(flag) is bool:
                writes += int(flag)
            else:
                count_known = False
                error("send has missing or invalid setting_write metadata", event)
            matches = (raw == expected_packet and event.get("action") == request["action"]
                       and type(flag) is bool and flag == request["setting_write"])
            if raw == expected_packet and flag != request["setting_write"]:
                count_known = False
            if not matches:
                error("logged send does not match the exact expected request", event)
            if sends != 1 or completions or disconnected or pending is not None:
                error("repeated, late, or interrupted control send", event)
            if connections != 1:
                error("control send lacks exactly one preceding connection", event)
            if matches and sends == 1 and not completions and not disconnected:
                result["sent"] = True
            pending = None
            continue
        if kind == "complete":
            completions += 1
            if completions != 1:
                error("multiple completion records", event)
            reported = event.get("setting_writes")
            if type(reported) is not int or reported < 0:
                count_known = False
                error("completion has missing or invalid setting_writes", event)
            elif count_known and reported != writes:
                count_known = False
                error("completion write count contradicts dispatch records", event)
            continue
        if kind in ("query", "drive_write"):
            count_known = False
            error("additional dispatch event in a one-request control exchange", event)
            continue
        if kind == "disconnected":
            disconnected = True
            error("device disconnected before normal exchange completion", event)
            continue
        if kind in ("error", "connection_failed", "service_error", "characteristic_error", "control_refused"):
            error(str(event.get("error") or event.get("message") or event.get("reason") or kind), event)
            continue
        if kind == "query_transport_ack":
            if event.get("error") is not None:
                error("GATT write failed: " + str(event["error"]), event)
            # A successful CoreBluetooth write callback is not a device ACK.
            continue
        if kind == "notification_state":
            uuid = event.get("uuid")
            if not isinstance(uuid, str):
                error("notification subscription event has invalid characteristic UUID", event)
            elif uuid.upper() == RX.upper() and event.get("error") is not None:
                error("control notification subscription failed: " + str(event["error"]), event)
            continue
        if kind != "notification" or not result["sent"]:
            # In particular, replies/fragments preceding the exact send are stale.
            continue
        if not isinstance(event.get("uuid"), str):
            error("notification has invalid characteristic UUID", event)
            continue
        if event["uuid"].upper() != RX.upper():
            continue
        if completions or disconnected:
            error("control notification arrived after exchange termination", event)
            continue
        if event.get("error") is not None:
            error("control notification failed: " + str(event["error"]), event)
            pending = None
            continue
        try:
            raw = _hex(event.get("hex"))
            frame = decode_frame(raw)
            if frame["forwarded"]:
                raise ValueError("forwarded frame cannot verify a direct exchange")
            command, count, index = frame["command"], frame["packet_count"], frame["packet_index"]
            if command not in (1, 2, 3):
                raise ValueError("unsupported response command")
            if count > MAX_FRAGMENTS or len(raw) - 8 > MAX_PAYLOAD:
                raise ValueError("response exceeds fragment or payload bound")
            payload = raw[8:]
            # A complete ACK can arrive between data fragments without changing
            # their order. Two fragment streams cannot be disambiguated safely.
            if command == 2 and count == 1 and pending is not None and pending["command"] != 2:
                payload_result(command, payload)
                continue
            if pending is not None:
                if command != pending["command"] or count != pending["count"] or index != len(pending["parts"]):
                    raise ValueError("inconsistent, duplicate, or reordered response fragment")
                pending["size"] += len(payload)
                if pending["size"] > MAX_PAYLOAD:
                    raise ValueError("reassembled response exceeds payload bound")
                pending["parts"].append(payload)
                if index != count - 1:
                    continue
                payload = b"".join(pending["parts"])
                pending = None
            elif count > 1:
                if index != 0:
                    raise ValueError("fragment stream did not start at index zero")
                pending = {"command": command, "count": count, "parts": [payload], "size": len(payload)}
                continue
            payload_result(command, payload)
        except (ValueError, TypeError, KeyError) as exc:
            error(str(exc), event)
            pending = None

    if sends != 1 or not result["sent"]:
        error("exchange lacks exactly one matching control send")
    if completions != 1:
        error("exchange lacks exactly one completion record")
    if pending is not None:
        error("incomplete fragmented response")
    if result["sent"] and request["command"] == 2 and not result["acknowledged"]:
        error("device protocol ACK was not observed")
    result["setting_writes"] = writes if count_known else None
    if result["errors"]:
        result["acknowledged"] = False
        result["feature_values"] = []
    return result
