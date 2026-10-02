"""Read-only preset inventory decoder derived from JBL One 2.7.9.

No SET builder. Rejects partial, reordered, or ambiguous multipart replies.
"""
import struct

from protocol import decode_frame

RX = "65786365-6C70-6F69-6E74-2E636F6D0001"
INVENTORY_QUERY = "00DD0100010002004034"


def parse_inventory(value: bytes) -> list[dict]:
    """V5GuitarPresetAllSimpleInfoList: repeated id, genre, UTF-8 length, name."""
    records = []
    pos = 0
    while pos < len(value):
        if pos + 3 > len(value):
            raise ValueError("truncated preset entry header")
        preset_id, genre, length = value[pos:pos + 3]
        pos += 3
        if pos + length > len(value):
            raise ValueError("truncated preset name")
        name = value[pos:pos + length].decode("utf-8", errors="strict")
        records.append({"preset_id": preset_id, "genre": genre, "name": name})
        pos += length
    return records


def inventory_result(events: list[dict]) -> dict:
    result = {"preset_list_verified": False, "presets": [], "inventory_errors": [], "inventory_frames": []}
    queried = False
    pending = None
    for event in events:
        if event.get("event") == "query":
            queried = event.get("hex") == INVENTORY_QUERY and event.get("purpose") == "get_preset_inventory_3440"
            pending = None
            continue
        if (not queried or event.get("event") != "notification" or event.get("uuid") != RX
                or event.get("error") is not None):
            continue
        try:
            raw = bytes.fromhex(event["hex"])
            frame = decode_frame(raw)
            if frame["command"] != 1 or frame["forwarded"]:
                continue
            count, index = frame["packet_count"], frame["packet_index"]
            if count > 1:
                if index == 0:
                    if pending is not None:
                        raise ValueError("overlapping fragmented GET replies")
                    pending = {"count": count, "parts": [raw[8:]], "times": [event.get("time")]}
                    continue
                if pending is None or pending["count"] != count or index != len(pending["parts"]):
                    raise ValueError("missing or reordered GET fragment")
                pending["parts"].append(raw[8:])
                pending["times"].append(event.get("time"))
                if index < count - 1:
                    continue
                payload = b"".join(pending["parts"])
                if len(payload) > 65535:
                    raise ValueError("inventory reply exceeds bounded decoder size")
                combined = struct.pack("<HHBBH", 0xDD00, 1, 1, 0, len(payload)) + payload
                frame = decode_frame(combined)
                frame["reassembled_packet_count"] = count
                frame["fragment_times"] = pending["times"]
                pending = None
            elif pending is not None:
                raise ValueError("single-packet GET interrupted fragmented reply")
            result["inventory_frames"].append({**frame, "time": event.get("time")})
            if frame.get("status") != 0:
                continue
            matches = [f for f in frame["features"] if f["id"] == "0x3440"]
            if len(matches) > 1:
                raise ValueError("duplicate preset inventory feature")
            if matches:
                result["presets"] = parse_inventory(bytes.fromhex(matches[0]["value_hex"]))
                result["preset_list_verified"] = True
        except (ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
            result["inventory_errors"].append({"time": event.get("time"), "error": str(exc)})
            pending = None
    if pending is not None:
        result["inventory_errors"].append({"error": "incomplete fragmented GET reply"})
    if result["inventory_errors"]:
        result["preset_list_verified"] = False
        result["presets"] = []
    return result
