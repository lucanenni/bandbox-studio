"""Named BandBox onboard controls derived from JBL One 2.7.9.

Pure request builders and feature-value decoders; no transport or I/O. Read
requests do not enter app pages. In particular, the app's looper page-entry
flow discards recorded audio and is deliberately not reproduced here.

The caller must validate frame status, reassemble fragments, correlate a direct
response after its request, and check device support. Matching a value here
does not establish transport causality or make an ACK a state observation.
See evidence/onboard-tools-protocol.md for source locations and limitations.
"""

from decimal import Decimal, InvalidOperation
import math
import struct


DRUM_PATTERNS = {
    "blues_1": 4, "blues_2": 5, "country": 6, "funk": 7,
    "metal": 8, "pop": 9, "punk": 10, "rnb": 11,
    "reggae": 12, "rock_1": 13, "rock_2": 14, "jazz": 15,
}
METRONOME_METERS = {"2/4": 0, "3/4": 1, "4/4": 2, "6/8": 3}
TUNER_MODES = {"auto": 0, **{f"string_{n}": n for n in range(1, 7)}}
TUNER_INSTRUMENTS = {
    "guitar_3_plus_3": 0, "guitar_6_in_line": 1,
    "bass_4_string": 2, "ukulele": 3,
}
TUNER_TUNINGS = {
    "standard": 0, "drop_d": 1, "full_step_down": 2, "half_step_up": 3,
    "open_c": 4, "open_d": 5, "open_e": 6, "open_f": 7, "open_g": 8,
    "open_a": 9, "drop_c_sharp": 10, "drop_c_sharp_alt_1": 11,
    "drop_c": 13, "drop_b": 14, "drop_a": 15, "dadgad": 16,
    "half_step_down": 17, "bass_standard": 18, "bass_drop_d": 19,
    "bass_drop_c": 20, "bass_bead": 32, "bass_full_step_down": 33,
    "bass_half_step_down": 34, "ukulele_standard": 25, "ukulele_low_g": 26,
    "ukulele_traditional": 35, "ukulele_english": 36, "ukulele_canadian": 28,
    "ukulele_baritone": 37, "ukulele_slide": 38, "ukulele_slack_key": 39,
}
LOOPER_PLAYBACK = {"stop": 0, "play": 1, "pause": 2, "resume": 3}
LOOPER_RECORDING = {
    "stop": 0, "start_first": 1, "start_second": 2, "start_third": 3,
    "undo": 4, "discard": 5, "cancel": 6,
}
INPUT_TYPES = {"unknown": 0, "mic": 1, "guitar": 2, "line_in": 3, "aux_instrument": 4}
PAGES = {"tuner": 1, "looper": 2, "drum": 3, "metronome": 4}
PAGE_STATES = {"not_in_use": 0, "device_in_use": 1, "app_in_use": 2}
SUPPORTED_FEATURES = {
    1: "chromatic_tuning", 2: "drum", 3: "looper_drum_mode",
    4: "looper_metronome_mode", 5: "output_phone_mode", 6: "output_usb_drive_mode",
    7: "scales", 8: "stereo", 9: "ukulele_tuner", 10: "looper",
    11: "three_level_guitar_gain", 12: "ai_track_type_bass", 13: "output_pc",
    14: "aux_out_setting",
}

# Only IV5Read / IV5WriteRead features appear in ordinary GET builders.
_READ_FEATURES = {
    "drum_enabled": 0x3000, "drum_bpm": 0x3001, "drum_pattern": 0x3002,
    "metronome_enabled": 0x3040, "metronome_bpm": 0x3041, "metronome_meter": 0x3042,
    "tuner_enabled": 0x3100, "tuner_mode": 0x3101, "tuner_instrument": 0x3102,
    "tuner_reference_hz": 0x3103, "tuner_tuning": 0x3104, "tuner_chromatic": 0x3107,
    "looper_recording_state": 0x3140, "looper_signal_interval": 0x3141,
    "looper_recorded_length": 0x3143, "looper_playback": 0x3145,
    "looper_position_ms": 0x3146, "looper_bars": 0x3147,
    "looper_layer_count": 0x3148, "looper_estimated_duration_ms": 0x314A,
    "looper_time_left_ms": 0x314B, "supported_features": 0x3805,
}
_BOOL_CONTROLS = {"drum_enabled", "metronome_enabled", "tuner_enabled", "tuner_chromatic"}
_ENUM_CONTROLS = {
    "drum_pattern": DRUM_PATTERNS, "metronome_meter": METRONOME_METERS,
    "tuner_mode": TUNER_MODES, "tuner_instrument": TUNER_INSTRUMENTS,
    "tuner_tuning": TUNER_TUNINGS, "looper_playback": LOOPER_PLAYBACK,
}
_BPM_CONTROLS = {"drum_bpm", "metronome_bpm"}
SETTABLE_CONTROLS = tuple(sorted(_BOOL_CONTROLS | _ENUM_CONTROLS.keys() | _BPM_CONTROLS | {"tuner_reference_hz"}))
READABLE_CONTROLS = tuple(sorted(_READ_FEATURES.keys() | {"channel_input", "channel_volume", "master_volume", "page_in_use"}))


def describe_controls() -> dict:
    """Return a fresh JSON-serializable catalog of the closed named API.

    Setter schemas describe accepted input, not firmware capability promises.
    Read-only ranges describe wire storage where the UI range is unverified.
    """
    readable = {}
    settable = {}
    for name in READABLE_CONTROLS:
        readable[name] = {"arguments": {}, "setting_write": False}
        if name in _READ_FEATURES:
            readable[name]["feature"] = _READ_FEATURES[name]
    for name in SETTABLE_CONTROLS:
        if name in _BOOL_CONTROLS:
            schema = {"type": "boolean"}
        elif name in _BPM_CONTROLS:
            schema = {"type": "integer", "minimum": 30, "maximum": 240, "unit": "bpm"}
        elif name in _ENUM_CONTROLS:
            schema = {"type": "string", "enum": list(_ENUM_CONTROLS[name])}
        else:
            schema = {"type": "number", "minimum": 420.0, "maximum": 460.0,
                      "multipleOf": 0.1, "unit": "Hz", "wire_scale": "integer tenths of Hz"}
        settable[name] = {"value": schema, "feature": _READ_FEATURES[name], "setting_write": True}
        readable[name]["value_description"] = dict(schema)
    readonly_values = {
        "looper_recording_state": {"type": "integer", "known_values": dict(LOOPER_RECORDING)},
        "looper_signal_interval": {"type": "integer", "unit": "not_verified", "wire_bits": 16},
        "looper_recorded_length": {"type": "integer", "unit": "ms", "wire_bits": 16},
        "looper_position_ms": {"type": "integer", "unit": "ms", "wire_bits": 16},
        "looper_bars": {"type": "integer", "unit": "bars",
                        "ui_choices": [1, 2, 4, 8, 12, 16, 24, 32], "write_available": False},
        "looper_layer_count": {"type": "integer", "unit": "layers", "wire_bits": 8},
        "looper_estimated_duration_ms": {"type": "integer", "unit": "ms", "wire_bits": 32},
        "looper_time_left_ms": {"type": "integer", "unit": "ms", "wire_bits": 32},
        "supported_features": {"type": "array", "items": "capability ID and known name; unknown IDs retained",
                               "known_values": dict(SUPPORTED_FEATURES)},
        "channel_input": {"type": "object", "fields": ["channel", "plugged", "input_type", "input_type_name"]},
        "channel_volume": {"type": "integer", "unit": "not_verified", "wire_bits": 8, "ui_range_verified": False},
        "master_volume": {"type": "integer", "unit": "not_verified", "wire_bits": 8, "ui_range_verified": False},
        "page_in_use": {"type": "object", "states": dict(PAGE_STATES)},
    }
    for name, description in readonly_values.items():
        readable[name]["value_description"] = description
    for name in ("channel_input", "channel_volume"):
        readable[name]["arguments"]["channel"] = {"type": "integer", "minimum": 1, "maximum": 4, "required": True}
    readable["channel_volume"]["arguments"]["input_type"] = {"type": "string", "enum": list(INPUT_TYPES), "required": True}
    readable["page_in_use"]["arguments"]["page"] = {"type": "string", "enum": list(PAGES), "required": True}
    readable["master_volume"]["scope"] = {"channel": 0, "input_type": "unknown"}
    for name, query_feature, response_feature in (
        ("channel_input", 0x3400, 0x3401), ("channel_volume", 0x3405, 0x3406),
        ("master_volume", 0x3405, 0x3406), ("page_in_use", 0x3803, 0x3804),
    ):
        readable[name].update(feature=query_feature, response_feature=response_feature)
    return {
        "source": "JBL One 2.7.9 APK; check actual device capabilities before use",
        "readable_controls": readable,
        "settable_controls": settable,
        "limitations": [
            "Only exact named choices are accepted by setters; enum integers are not accepted.",
            "Known read enums and ranges are descriptive; unknown/out-of-range read values remain visible.",
            "Tuner tuning should match the chosen instrument; these setters do not change other settings automatically.",
            "Use the separate guarded MCP tools for recording, bars and mixer volume. Mixer EQ, page ownership and destructive writes are not exposed.",
            "A response match still requires the caller to verify transport status and request causality.",
        ],
    }


def _enum_value(value, choices: dict, name: str) -> int:
    if not isinstance(value, str) or value not in choices:
        raise ValueError(f"{name} must be one of: {', '.join(choices)}")
    return choices[value]


def _integer(value, lower: int, upper: int, name: str) -> int:
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(f"{name} must be an integer from {lower} to {upper}")
    return value


def _request(action: str, command: int, feature: int, response_feature: int,
             setting_write: bool, value: bytes | None = None) -> dict:
    result = {"action": action, "command": command, "feature": feature,
              "setting_write": setting_write, "response_feature": response_feature}
    if value is not None:
        result["value_hex"] = value.hex().upper()
    return result


def build_read(control: str, *, channel: int | None = None,
               input_type: str | None = None, page: str | None = None) -> dict:
    """Build one named read; parameterized query features use command 2.

    Channel inputs are 1..4. For channel volume, first read its current input
    type, then pass its named input_type. Master volume has its own fixed
    scope [Master=0, Unknown=0]. These requests never change a setting.
    """
    if not isinstance(control, str) or control not in READABLE_CONTROLS:
        raise ValueError("unknown or unsupported read control")
    if control in _READ_FEATURES:
        if any(arg is not None for arg in (channel, input_type, page)):
            raise ValueError("this read does not accept channel, input_type, or page")
        feature = _READ_FEATURES[control]
        return _request(f"read_{control}", 1, feature, feature, False)
    if control == "master_volume":
        if any(arg is not None for arg in (channel, input_type, page)):
            raise ValueError("master_volume has a fixed scope")
        return _request("read_master_volume", 2, 0x3405, 0x3406, False, b"\x00\x00")
    if control == "page_in_use":
        if channel is not None or input_type is not None:
            raise ValueError("page_in_use does not accept channel or input_type")
        func = _enum_value(page, PAGES, "page")
        return _request("read_page_in_use", 2, 0x3803, 0x3804, False, bytes([func]))
    if page is not None:
        raise ValueError("channel reads do not accept page")
    ch = _integer(channel, 1, 4, "channel")
    if control == "channel_input":
        if input_type is not None:
            raise ValueError("channel_input does not accept input_type")
        return _request("read_channel_input", 2, 0x3400, 0x3401, False, bytes([ch]))
    kind = _enum_value(input_type, INPUT_TYPES, "input_type")
    return _request("read_channel_volume", 2, 0x3405, 0x3406, False, bytes([ch, kind]))


def build_set(control: str, value) -> dict:
    """Build one validated setting change, without saving a preset or loop.

    Tuner reference accepts numeric Hz at 0.1-Hz resolution. Other numeric
    settings require integer values; enum settings require the named choice.
    Recording, bars, page claims, signal interval, mixer, EQ, and destructive
    operations are intentionally unavailable pending their additional proof.
    """
    if not isinstance(control, str) or control not in SETTABLE_CONTROLS:
        raise ValueError("unsupported or unverified setting; no request created")
    if control in _BOOL_CONTROLS:
        if type(value) is not bool:
            raise ValueError(f"{control} must be a boolean")
        encoded = bytes([int(value)])
    elif control in _BPM_CONTROLS:
        encoded = bytes([_integer(value, 30, 240, "BPM")])
    elif control in _ENUM_CONTROLS:
        encoded = bytes([_enum_value(value, _ENUM_CONTROLS[control], control)])
    else:
        if type(value) not in (int, float, Decimal):
            raise ValueError("tuner reference must be numeric Hz")
        try:
            hz = Decimal(str(value))
            raw = hz * 10
            if not hz.is_finite() or not 420 <= hz <= 460 or raw != raw.to_integral_value():
                raise ValueError("tuner reference must be 420.0..460.0 Hz in 0.1-Hz steps")
            encoded = struct.pack("<H", int(raw))
        except InvalidOperation as exc:
            raise ValueError("invalid tuner reference") from exc
    feature = _READ_FEATURES[control]
    return _request(f"set_{control}", 2, feature, feature, True, encoded)


def _length(value: bytes, expected: int) -> None:
    if len(value) != expected:
        raise ValueError(f"feature requires exactly {expected} value bytes")


def _bool(value: int) -> bool:
    if value not in (0, 1):
        raise ValueError("noncanonical boolean byte")
    return bool(value)


def _name(choices: dict, value: int) -> str | None:
    return next((name for name, number in choices.items() if number == value), None)


def decode_response(feature: int, value: bytes) -> dict:
    """Decode one complete feature value; preserve unknown enum/capability IDs.

    This also decodes unsolicited tuner/looper measurements and beat events.
    Their IV5Payload classes do not prove that they support a GET request.
    Units absent from the APK field names remain explicitly unverified.
    """
    if type(feature) is not int or not isinstance(value, bytes):
        raise TypeError("feature must be int and value must be bytes")
    result = {"feature": feature, "raw_hex": value.hex().upper()}
    control = next((name for name, number in _READ_FEATURES.items() if number == feature), None)
    if control is not None:
        result["control"] = control
    if control in _BOOL_CONTROLS:
        _length(value, 1)
        result["value"] = _bool(value[0])
    elif control in _ENUM_CONTROLS or feature == 0x3140:
        _length(value, 1)
        choices = LOOPER_RECORDING if feature == 0x3140 else _ENUM_CONTROLS[control]
        result.update(value=value[0], name=_name(choices, value[0]))
    elif control in _BPM_CONTROLS:
        _length(value, 1)
        result.update(value=value[0], unit="bpm", within_ui_range=30 <= value[0] <= 240)
    elif feature == 0x3103:
        _length(value, 2)
        raw = int.from_bytes(value, "little")
        result.update(value=raw / 10, raw_value=raw, unit="Hz", within_ui_range=4200 <= raw <= 4600)
    elif feature in (0x3147, 0x3148):
        _length(value, 1)
        result["value"] = value[0]
        if feature == 0x3147:
            result["within_ui_choices"] = value[0] in (1, 2, 4, 8, 12, 16, 24, 32)
    elif feature in (0x3141, 0x3143, 0x3146, 0x3149, 0x314A, 0x314B):
        _length(value, 4 if feature in (0x314A, 0x314B) else 2)
        result["value"] = int.from_bytes(value, "little")
        result["unit"] = "ms" if feature in (0x3143, 0x3146, 0x3149, 0x314A, 0x314B) else "not_verified"
    elif feature == 0x3805:
        result["capabilities"] = [{"id": number, "name": SUPPORTED_FEATURES.get(number)} for number in value]
    elif feature == 0x3401:
        _length(value, 3)
        result.update(channel=value[0], plugged=_bool(value[1]), input_type=value[2], input_type_name=_name(INPUT_TYPES, value[2]))
    elif feature == 0x3406:
        _length(value, 3)
        result.update(channel=value[0], input_type=value[1], input_type_name=_name(INPUT_TYPES, value[1]), value=value[2], unit="not_verified")
    elif feature == 0x3804:
        _length(value, 2)
        result.update(page=value[0], page_name=_name(PAGES, value[0]), state=value[1], state_name=_name(PAGE_STATES, value[1]))
    elif feature == 0x3106:
        _length(value, 10)
        frequency, mode, measurement, signal = struct.unpack("<fBfB", value)
        if not math.isfinite(frequency) or not math.isfinite(measurement):
            raise ValueError("non-finite tuner measurement")
        result.update(frequency=frequency, tuner_mode=mode, tuner_mode_name=_name(TUNER_MODES, mode),
                      result=measurement, result_unit="not_verified", has_signal=_bool(signal))
    elif feature == 0x3142:
        _length(value, 4)
        signal = struct.unpack("<f", value)[0]
        if not math.isfinite(signal):
            raise ValueError("non-finite looper signal")
        result.update(value=signal, unit="not_verified")
    elif feature in (0x3003, 0x3043):
        _length(value, 0)
        result["event"] = "drum_tap" if feature == 0x3003 else "metronome_tap"
    else:
        raise ValueError("unsupported response feature")
    return result


def response_matches(request: dict, feature: int, value: bytes) -> bool:
    """Match a decoded feature to its named request, without transport claims.

    A setting change requires the exact device value, not merely an ACK.
    Parameterized reads require their channel/input/page prefix to match.
    The caller is responsible for reply freshness and request/response order.
    """
    try:
        if type(feature) is not int or feature != request["response_feature"]:
            return False
        decode_response(feature, value)
        if request["setting_write"] is True:
            return request["action"] in {f"set_{name}" for name in SETTABLE_CONTROLS} and value == bytes.fromhex(request["value_hex"])
        if request["setting_write"] is not False:
            return False
        action = request["action"]
        if action in ("read_channel_input", "read_channel_volume", "read_master_volume", "read_page_in_use"):
            return request["command"] == 2 and value.startswith(bytes.fromhex(request["value_hex"]))
        return (request["command"] == 1 and action.startswith("read_")
                and _READ_FEATURES.get(action[5:]) == feature == request["feature"])
    except (KeyError, TypeError, ValueError):
        return False
