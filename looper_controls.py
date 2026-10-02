"""Pure guarded looper requests; no transport, page entry, or destructive ops.

The caller gathers verified GET replies from the same device while holding its
device lease, then supplies flat decoded control values plus ``verified=True``
and ``age_seconds`` (age of the oldest required reply at the time of this call).
Neither user assertions nor cached app defaults qualify as a verified state.
The caller must send promptly without releasing the lease, require a successful
ACK and matching device report, and never retry an ambiguous recording request.

Operation GET semantics and firmware support must be checked by actual replies;
the guards below are a conservative policy, not a firmware transaction lock.
See evidence/looper-recording.md for exact APK evidence and its limits.
"""

import math


MAX_STATE_AGE_SECONDS = 30
DRUM_BARS = (4, 8, 12, 16, 24, 32)
METRONOME_BARS = (1, 2, 4, 8, 12, 16, 24, 32)


def _integer(value, lower, upper, name):
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(f"{name} must be an integer from {lower} to {upper}")
    return value


def _fresh(state):
    if not isinstance(state, dict) or state.get("verified") is not True:
        raise ValueError("fresh verified device state is required; no request created")
    age = state.get("age_seconds")
    if (type(age) not in (int, float) or not math.isfinite(age)
            or not 0 <= age <= MAX_STATE_AGE_SECONDS):
        raise ValueError("device state is missing or older than 30 seconds; no request created")


def _state_integer(state, name, lower, upper):
    return _integer(state.get(name), lower, upper, name)


def _empty(state):
    for name, maximum in (("looper_recording_state", 6),
                          ("looper_recorded_length", 65535),
                          ("looper_layer_count", 255)):
        if _state_integer(state, name, 0, maximum) != 0:
            raise ValueError("looper must be empty and not recording; no request created")


def _generators(state):
    values = tuple(state.get(name) for name in ("drum_enabled", "metronome_enabled"))
    if any(type(value) is not bool for value in values):
        raise ValueError("verified drum and metronome booleans are required")
    return values


def _request(action, feature, value):
    return {"action": action, "command": 2, "feature": feature,
            "value_hex": bytes([value]).hex().upper(), "setting_write": True,
            "response_feature": feature}


def build_recording_start(state):
    """Start one new freehand recording on an empty, stopped device.

    Required flat state keys: looper_recording_state=0, looper_playback=0,
    looper_recorded_length=0 (ms), looper_layer_count=0, drum_enabled=False,
    metronome_enabled=False, verified=True, age_seconds<=30. This does not
    discard, select a mode, start a backing track, or schedule an automatic stop.
    Start1st is also an overdub command on a nonempty device, hence all guards.
    """
    _fresh(state)
    _empty(state)
    if _state_integer(state, "looper_playback", 0, 3) != 0:
        raise ValueError("playback must be stopped before a new freehand recording")
    if any(_generators(state)):
        raise ValueError("drums and metronome must be stopped before freehand recording")
    return _request("looper_record_start", 0x3140, 1)


def build_recording_stop(state):
    """Stop a known active recording, preserving its recorded content.

    Only verified, recent looper_recording_state=1/2/3 is accepted. These are
    freehand/drum/metronome start operations, not the number of recorded layers.
    Stop can be followed by loop playback; it is not a promise of silence.
    """
    _fresh(state)
    if _state_integer(state, "looper_recording_state", 0, 6) not in (1, 2, 3):
        raise ValueError("a known active recording is required before stopping")
    return _request("looper_record_stop", 0x3140, 0)


def build_bars(value, state):
    """Set bars only in the matching backing preview without recorded content.

    In addition to fresh empty state, require mode='drum' or 'metronome', the
    matching generator enabled and the other disabled, known looper_playback,
    looper_bars, and looper_estimated_duration_ms. The candidate must fit the
    app's 60-second limit. No other setting is changed to make it fit.
    """
    _fresh(state)
    _empty(state)
    _state_integer(state, "looper_playback", 0, 3)
    mode = state.get("mode")
    if mode not in ("drum", "metronome"):
        raise ValueError("mode must be drum or metronome")
    drum, metronome = _generators(state)
    if (drum, metronome) != ((True, False) if mode == "drum" else (False, True)):
        raise ValueError("the chosen backing preview must be enabled, and the other stopped")
    allowed = DRUM_BARS if mode == "drum" else METRONOME_BARS
    value = _integer(value, 1, 32, "bars")
    current = _state_integer(state, "looper_bars", 1, 32)
    if value not in allowed or current not in allowed:
        raise ValueError("bar count is unsupported for the chosen mode")
    duration = _state_integer(state, "looper_estimated_duration_ms", 1, 0xFFFFFFFF)
    per_bar = duration // current
    if per_bar == 0 or per_bar * value > 60000:
        raise ValueError("requested bars do not fit the verified duration and 60-second limit")
    if value == current:
        raise ValueError("bar count already matches; no request created")
    return _request("looper_bars", 0x3147, value)


def response_matches(request, feature, value):
    """Match the exact post-send feature value; ACK/order are caller concerns.

    Stop's matching operation report alone does not prove a usable recording;
    read recorded length afterward to establish that separately.
    """
    try:
        expected_feature, allowed = {
            "looper_record_start": (0x3140, (1,)),
            "looper_record_stop": (0x3140, (0,)),
            "looper_bars": (0x3147, METRONOME_BARS),
        }[request["action"]]
        encoded = bytes.fromhex(request["value_hex"])
        return (type(feature) is int and isinstance(value, bytes)
                and request["command"] == 2 and request["setting_write"] is True
                and feature == request["feature"] == request["response_feature"] == expected_feature
                and len(encoded) == 1 and encoded[0] in allowed and value == encoded)
    except (KeyError, TypeError, ValueError):
        return False
