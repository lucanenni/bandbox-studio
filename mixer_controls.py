"""Pure, guarded BandBox master/channel volume builders.

JBL's public BandBox dashboard uses integer mixer steps 0..32, passed unchanged
through JBL One's bridge to feature 0x3406. These are not percentages. The
separate model_config.json max_volume=100 does not override the mixer widget.
See evidence/mixer-volume-protocol.md for source paths and hashes.

Callers must obtain matching fresh 0x3401 input and 0x3406 volume responses in
the same exclusive connection/lease as the write. This module checks their
contents, not provenance or freshness. It performs no I/O and cannot query the
device. A current volume outside the source UI range blocks a write rather
than guessing a conversion or clamping the device's value.
"""

from onboard_controls import decode_response


FEATURE = 0x3406
MIN_VOLUME = 0
MAX_VOLUME = 32
# Source-supported input pairings used by the Trio app. Unknown/new pairings
# remain readable through the generic decoder but cannot be written here.
_CHANNEL_INPUTS = {1: {1, 2}, 2: {1, 3}, 3: {2}, 4: {4}}


def describe_controls() -> dict:
    value = {"type": "integer", "minimum": MIN_VOLUME, "maximum": MAX_VOLUME,
             "unit": "raw_mixer_steps", "percentage": False}
    return {
        "settable_controls": {
            "master_volume": {"value": dict(value), "requires": ["fresh matching master volume response within 0..32"]},
            "channel_volume": {"value": dict(value), "channel": {"type": "integer", "minimum": 1, "maximum": 4},
                               "requires": ["fresh matching plugged channel input", "fresh matching volume response within 0..32"]},
        },
        "source": "JBL BandBox public dashboard index.282b0bc4.js + JBL One 2.7.9 bridge/serializer",
        "hardware_scale_verified": False,
    }


def _integer(value, minimum: int, maximum: int, name: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer from {minimum} to {maximum}")
    return value


def decode_volume(value: bytes) -> dict:
    """Retain any valid unsigned wire value, labeling the source UI range."""
    result = decode_response(FEATURE, value)
    result.update(unit="raw_mixer_steps", ui_range=[MIN_VOLUME, MAX_VOLUME],
                  within_ui_range=MIN_VOLUME <= result["value"] <= MAX_VOLUME)
    return result


def build_set(control: str, value: int, *, current_volume: bytes,
              channel: int | None = None, input_status: bytes | None = None) -> dict:
    """Build a named mixer setting from fresh responses supplied by the caller.

    current_volume is the complete feature-0x3406 value (three bytes).
    For channel_volume, input_status is a feature-0x3401 value (three bytes),
    with a plugged, supported input. The channel/input tuple must match both.
    Master volume always uses tuple [0,0] and accepts no channel/input argument.
    """
    if control not in ("master_volume", "channel_volume"):
        raise ValueError("unsupported mixer setting")
    target = _integer(value, MIN_VOLUME, MAX_VOLUME, "raw mixer steps")
    if control == "master_volume":
        if channel is not None or input_status is not None:
            raise ValueError("master_volume has fixed channel/input scope [0,0]")
        scope = (0, 0)
    else:
        ch = _integer(channel, 1, 4, "channel")
        state = decode_response(0x3401, input_status)
        if state["channel"] != ch:
            raise ValueError("channel input response does not match requested channel")
        if state["plugged"] is not True:
            raise ValueError("channel input is not plugged; no setting request created")
        if state["input_type"] not in _CHANNEL_INPUTS[ch]:
            raise ValueError("channel input pairing is unknown or not source-supported")
        scope = (ch, state["input_type"])
    baseline = decode_volume(current_volume)
    if (baseline["channel"], baseline["input_type"]) != scope:
        raise ValueError("volume response does not match the current channel/input scope")
    if not baseline["within_ui_range"]:
        raise ValueError("current mixer value is outside verified 0..32 UI steps; firmware scale requires investigation")
    return {
        "action": f"set_{control}", "command": 2, "feature": FEATURE,
        "value_hex": bytes((*scope, target)).hex().upper(),
        "setting_write": True, "response_feature": FEATURE,
    }


def response_matches(request: dict, feature: int, value: bytes) -> bool:
    """Require an exact device state echo; caller still verifies causality."""
    try:
        if (type(feature) is not int or feature != FEATURE
                or request["feature"] != FEATURE or request["response_feature"] != FEATURE
                or request["command"] != 2 or request["setting_write"] is not True):
            return False
        actual = decode_volume(value)
        if not actual["within_ui_range"]:
            return False
        if request["action"] == "set_master_volume":
            if (actual["channel"], actual["input_type"]) != (0, 0):
                return False
        elif request["action"] == "set_channel_volume":
            if actual["input_type"] not in _CHANNEL_INPUTS.get(actual["channel"], set()):
                return False
        else:
            return False
        return value == bytes.fromhex(request["value_hex"])
    except (KeyError, TypeError, ValueError):
        return False
