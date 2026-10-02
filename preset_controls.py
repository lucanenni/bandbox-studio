"""Pure JBL One 2.7.9 preset command builders; no transport or device access.

See evidence/preset-operations.md. Callers must check current inventory and
selection, serialize requests, and require ACK plus matching report/readback.
An operation report alone does not prove persistence. Do not retry creation
after an ambiguous timeout. The factory-save block below is project policy.
"""
from collections.abc import Iterable, Mapping

_OPERATIONS = {"duplicate": 1, "rename": 3, "save_user_preset": 4, "save_as": 9}
_CREATIONS = {"duplicate", "save_as"}


def _id(value: int, label: str) -> int:
    if type(value) is not int or not 0 <= value < 255:
        raise ValueError(f"{label} must be an integer in 0..254; 255 is omitted")
    return value


def _channel(value: int) -> int:
    if type(value) is not int or value not in (1, 3):
        raise ValueError("guitar channel must be 1 or 3")
    return value


def _name(value: str) -> bytes:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("preset name must be a nonblank string")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError("preset name must be valid UTF-8") from exc
    if len(encoded) > 255:
        raise ValueError("preset name exceeds the one-byte UTF-8 length field")
    return encoded


def _descriptor(action: str, feature: int, value: bytes) -> dict:
    return {"action": action, "command": 2, "feature": feature,
            "value_hex": value.hex().upper(), "setting_write": True,
            "response_feature": feature}


def select(channel: int, preset_id: int) -> dict:
    """Select an inventoried preset; this can discard unsaved preview edits."""
    return _descriptor("select", 0x3442,
                       bytes((_channel(channel), _id(preset_id, "preset_id"))))


def _operation(action: str, channel: int, source_id: int,
               name: str | None = None, genre: int | None = None) -> dict:
    channel, source_id = _channel(channel), _id(source_id, "source_id")
    if action == "save_user_preset" and source_id < 51:
        raise ValueError("factory preset overwrite is blocked; create a user copy first")
    encoded = b"" if name is None else _name(name)
    genre_byte = 255 if genre is None else _id(genre, "genre")
    value = bytes((channel, _OPERATIONS[action], source_id, 255,
                   genre_byte, len(encoded))) + encoded
    return _descriptor(action, 0x3446, value)


def duplicate(channel: int, source_id: int, name: str, genre: int) -> dict:
    """Duplicate the currently selected source; the device assigns the new ID."""
    _name(name)
    _id(genre, "genre")
    return _operation("duplicate", channel, source_id, name, genre)


def save_as(channel: int, source_id: int, name: str, genre: int) -> dict:
    """Save As from the currently selected source; do not invent a destination ID."""
    _name(name)
    _id(genre, "genre")
    return _operation("save_as", channel, source_id, name, genre)


def rename(channel: int, preset_id: int, name: str) -> dict:
    """Rename the currently selected preset without changing its ID."""
    _name(name)
    return _operation("rename", channel, preset_id, name)


def save_user_preset(channel: int, preset_id: int) -> dict:
    """Persist the entire selected preview, only for user IDs 51..254."""
    return _operation("save_user_preset", channel, preset_id)


def _bytes(value: bytes | str) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        try:
            return bytes.fromhex(value)
        except ValueError as exc:
            raise ValueError("operation value is not valid hexadecimal") from exc
    raise ValueError("operation value must be bytes or a hexadecimal string")


def _fields(value: bytes | str) -> dict:
    raw = _bytes(value)
    if len(raw) < 6 or len(raw) != 6 + raw[5]:
        raise ValueError("operation response length does not match its name field")
    try:
        name = raw[6:].decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("operation response name is not valid UTF-8") from exc
    return {"channel": _channel(raw[0]), "operation": raw[1],
            "source_id": None if raw[2] == 255 else raw[2],
            "new_preset_id": None if raw[3] == 255 else raw[3],
            "genre": None if raw[4] == 255 else raw[4], "name": name}


def parse_operation_response(value: bytes | str, expected: Mapping,
                             existing_ids: Iterable[int] | None = None) -> dict:
    """Match a 3446 value against a builder result, after transport validation.

    Rejects another action/channel/source or different requested name/genre.
    Creation alone may omit source (FF), as observed on the Trio; this requires
    prior inventory containing the requested source and excluding the new ID.
    The returned source_id stays None and requested_source_id names the request.
    A creation must return a distinct non-FF ID; supply the prior inventory's
    IDs to reject reuse of an existing ID. Does not consume status/TLV headers
    or verify ACK, freshness, selected preset, inventory, or saved content.
    """
    if not isinstance(expected, Mapping) or expected.get("action") not in _OPERATIONS:
        raise ValueError("expected must be a supported preset operation descriptor")
    action = expected["action"]
    requested = _fields(expected.get("value_hex"))
    if requested["new_preset_id"] is not None:
        raise ValueError("request cannot assign a destination preset ID")
    name = requested["name"] if action != "save_user_preset" else None
    genre = requested["genre"] if action in _CREATIONS else None
    if action in _CREATIONS:
        _id(genre, "genre")
    canonical = _operation(action, requested["channel"], requested["source_id"], name, genre)
    if dict(expected) != canonical:
        raise ValueError("expected descriptor differs from its named command builder")
    report = _fields(value)
    for key in ("channel", "operation"):
        if report[key] != requested[key]:
            raise ValueError(f"operation response has a different {key}")
    prior = None if existing_ids is None else {_id(item, "existing preset ID") for item in existing_ids}
    source_omitted = report["source_id"] is None
    if source_omitted:
        if (action not in _CREATIONS or prior is None
                or requested["source_id"] not in prior):
            raise ValueError("omitted source is allowed only for creation bound to prior inventory")
    elif report["source_id"] != requested["source_id"]:
        raise ValueError("operation response has a different source_id")
    if action != "save_user_preset" and report["name"] != requested["name"]:
        raise ValueError("operation response has a different name")
    if action in _CREATIONS:
        if report["genre"] != requested["genre"]:
            raise ValueError("operation response has a different genre")
        new_id = report["new_preset_id"]
        if new_id is None or new_id == requested["source_id"]:
            raise ValueError("creation did not return a distinct destination ID")
        if prior is not None and new_id in prior:
            raise ValueError("creation returned an ID already in the prior inventory")
    result = {"action": action, **report}
    if source_omitted:
        result["requested_source_id"] = requested["source_id"]
    return result
