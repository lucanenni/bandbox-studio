"""Strict decoder for the Protocol 4 frames actually observed on this BandBox.

The header follows OpenJBL. The response status/TLV layout was observed on
this device. Feature semantics remain unverified. There are no SET builders.
"""
import struct


def decode_frame(raw: bytes) -> dict:
    if len(raw) < 8:
        raise ValueError("truncated Protocol 4 header")
    identifier, command, count, index, size = struct.unpack("<HHBBH", raw[:8])
    if identifier not in (0xDD00, 0xDD01):
        raise ValueError("unrecognized frame identifier")
    if count == 0 or index >= count:
        raise ValueError("invalid fragment count/index")
    if len(raw) != size + 8:
        raise ValueError("frame payload length mismatch")
    result = {
        "command": command, "kind": {1: "get_response", 3: "unsolicited_notification"}.get(command, "other"),
        "packet_count": count, "packet_index": index, "forwarded": identifier == 0xDD01,
        "payload_hex": raw[8:].hex().upper(), "features": [],
    }
    if count != 1 or index != 0:
        result["decode_status"] = "fragmented frame preserved; not interpreted"
        return result
    if command not in (1, 3):
        result["decode_status"] = "unrecognized command preserved; not interpreted"
        return result
    payload = raw[8:]
    if len(payload) < 2:
        raise ValueError("missing response status")
    status = struct.unpack_from("<H", payload)[0]
    result["status"] = status
    if status != 0:
        result["decode_status"] = "nonzero device status; not interpreted"
        return result
    pos = 2
    while pos < len(payload):
        if pos + 4 > len(payload):
            raise ValueError("truncated feature header")
        feature, length = struct.unpack_from("<HH", payload, pos)
        pos += 4
        if pos + length > len(payload):
            raise ValueError("truncated feature value")
        value = payload[pos:pos + length]
        pos += length
        result["features"].append({
            "id": f"0x{feature:04X}", "value_hex": value.hex().upper(),
            "unsigned_byte": value[0] if len(value) == 1 else None,
            "meaning": "unverified",
        })
    result["decode_status"] = "observed status/TLV layout"
    return result


def summarize(events: list[dict]) -> dict:
    frames, errors = [], []
    query_sent = False
    verified = False
    for event in events:
        if event.get("event") == "query":
            query_sent = event.get("purpose") == "get_observed_feature_000D" and event.get("hex") == "00DD0100010002000D00"
        if event.get("event") != "notification":
            continue
        if event.get("uuid") != "65786365-6C70-6F69-6E74-2E636F6D0001" or event.get("error") is not None:
            continue
        try:
            decoded = decode_frame(bytes.fromhex(event["hex"]))
        except (ValueError, KeyError, TypeError) as exc:
            errors.append({"time": event.get("time"), "error": str(exc), "raw_hex": event.get("hex")})
        else:
            frames.append({**decoded, "time": event.get("time"), "raw_hex": event["hex"]})
            # Accept only a matching feature response that arrived after our GET.
            if (query_sent and not decoded["forwarded"] and decoded["kind"] == "get_response"
                    and decoded.get("status") == 0 and decoded["packet_count"] == 1
                    and any(v["id"] == "0x000D" and len(v["value_hex"]) == 2 for v in decoded["features"])):
                verified = True
    # A transport ack or unsolicited notification alone never counts as a query reply.
    return {
        "connected": any(e.get("event") == "connected" for e in events),
        "query_response_verified": verified,
        "frames": frames, "decode_errors": errors,
        "setting_writes": 0, "gain_control_available": False, "preset_control_available": False,
    }
