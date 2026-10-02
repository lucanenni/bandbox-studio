"""APK-backed effect packet builders and reply matching; no device transport."""
import json
import math
from pathlib import Path
import struct


CATALOG = json.loads(Path(__file__).with_name("effect_catalog.json").read_text())
MODELS = {item["model_id"]: item for item in CATALOG["models"]}
FEATURE = 0x3445


def _integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label} must be an integer from {low} to {high}.")
    return value


def _model(channel, preset_id, slot_id, model_id):
    _integer(channel, 1, 4, "Channel")
    _integer(preset_id, 1, 254, "Preset ID")
    _integer(slot_id, 0, 7, "Slot ID")
    if type(model_id) is not str or model_id not in MODELS:
        raise ValueError("Unknown model ID; use a model_id from the effect catalog.")
    model = MODELS[model_id]
    if model["slot_id"] != slot_id:
        raise ValueError("Model is not allowed in this slot by JBL One.")
    return model


def _bypass(active):
    if type(active) is not bool:
        raise ValueError("Active must be an explicit Boolean.")
    return 0 if active else 1


def _parameters(model):
    return {p["parameter_id"]: p for p in model["parameters"]}


def _float_bytes(parameter):
    value = parameter.get("value")
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Snapshot parameter must have a finite numeric value.")
    try:
        packed = struct.pack("<f", value)
        supplied = parameter.get("value_hex")
        if supplied is not None:
            if type(supplied) is not str:
                raise ValueError("Invalid raw float bytes.")
            raw = bytes.fromhex(supplied)
            if len(raw) != 4 or raw != packed:
                raise ValueError("Snapshot value and raw float bytes disagree.")
            return raw
        return packed
    except (OverflowError, struct.error) as exc:
        raise ValueError("Snapshot value cannot be encoded as float32.") from exc


def _snapshot(snapshot, slot_id, model):
    if not isinstance(snapshot, dict):
        raise ValueError("A complete reported slot snapshot is required.")
    for field, expected in (("slot_id", slot_id), ("algorithm_id", model["algorithm_id"]),
                            ("config_id", model["config_id"])):
        if type(snapshot.get(field)) is not int or snapshot[field] != expected:
            raise ValueError("Snapshot slot or model does not match the request.")
    _integer(snapshot.get("bypass_raw"), 0, 1, "Snapshot bypass")
    values = snapshot.get("parameters")
    if not isinstance(values, list) or type(snapshot.get("parameter_count")) is not int:
        raise ValueError("Snapshot must include the complete parameter list and count.")
    if snapshot["parameter_count"] != len(values) or len(values) > 255:
        raise ValueError("Snapshot parameter count differs from the supplied list.")
    definitions = _parameters(model)
    seen = set()
    encoded = []
    for parameter in values:
        if not isinstance(parameter, dict):
            raise ValueError("Invalid snapshot parameter entry.")
        identifier = _integer(parameter.get("parameter_id"), 0, 254, "Parameter ID")
        if identifier in seen or identifier not in definitions:
            raise ValueError("Duplicate or undefined parameter in snapshot.")
        seen.add(identifier)
        raw = _float_bytes(parameter)
        number = struct.unpack("<f", raw)[0]
        definition = definitions[identifier]
        if not definition["wire_min"] <= number <= definition["wire_max"]:
            raise ValueError("Snapshot parameter is outside its defined range.")
        encoded.append((identifier, raw))
    return encoded


def _action(name, channel, preset_id, slot_id, model, change, bypass_raw, values, **expected):
    payload = bytes([channel, preset_id, change, slot_id, model["algorithm_id"],
                     model["config_id"], bypass_raw, len(values)])
    payload += b"".join(bytes([identifier]) + raw for identifier, raw in values)
    return {"action": name, "command": 2, "feature": FEATURE,
            "value_hex": payload.hex().upper(), "setting_write": True,
            "response_feature": FEATURE,
            "expected": {"channel": channel, "preset_id": preset_id, "slot_id": slot_id,
                         "model_id": model["model_id"], "change": change, **expected}}


def set_parameter(channel, preset_id, slot_id, model_id, parameter_id, ui_value, active, snapshot):
    """Send one UI-integer parameter; preserve confirmed model and bypass.

    The snapshot must contain the parameter. UI integers map directly to wire
    float except Compressor Ratio, whose UI integer is divided by ten.
    """
    model = _model(channel, preset_id, slot_id, model_id)
    bypass = _bypass(active)
    values = _snapshot(snapshot, slot_id, model)
    if snapshot["bypass_raw"] != bypass:
        raise ValueError("Snapshot bypass differs from the confirmed active state.")
    _integer(parameter_id, 0, 254, "Parameter ID")
    definition = _parameters(model).get(parameter_id)
    if definition is None or parameter_id not in {identifier for identifier, _ in values}:
        raise ValueError("Parameter is not defined and present in this reported slot.")
    _integer(ui_value, definition["ui_min"], definition["ui_max"], "UI value")
    raw = struct.pack("<f", ui_value * definition["wire_multiplier"])
    return _action("set_effect_parameter", channel, preset_id, slot_id, model, 4, bypass,
                   [(parameter_id, raw)], parameter_id=parameter_id,
                   value_hex=raw.hex().upper(), bypass=bypass)


def set_model(channel, preset_id, slot_id, current_model_id, target_model_id):
    """Select one allowed model, letting the device supply its parameter values."""
    current = _model(channel, preset_id, slot_id, current_model_id)
    target = _model(channel, preset_id, slot_id, target_model_id)
    if current_model_id == target_model_id:
        raise ValueError("That model is already selected; no setting packet needed.")
    return _action("set_effect_model", channel, preset_id, slot_id, target,
                   current["model_change_code"], 255, [])


def set_bypass(channel, preset_id, slot_id, model_id, active, snapshot):
    """Set bypass while retaining the complete current list, as the app does.

    Caller must supply current preview values; saved preset values may differ.
    Raw float bytes and parameter order are retained exactly.
    """
    model = _model(channel, preset_id, slot_id, model_id)
    bypass = _bypass(active)
    values = _snapshot(snapshot, slot_id, model)
    if snapshot["bypass_raw"] == bypass:
        raise ValueError("The slot already has that active state; no setting packet needed.")
    return _action("set_effect_bypass", channel, preset_id, slot_id, model, 1, bypass,
                   values, bypass=bypass)


def match_reply(action, value_hex):
    """Match one complete 3445 TLV value. Transport must separately require ACK.

    This checks device-reported fields, not freshness or audio/DSP behavior.
    The transport must establish that the reply follows this exact request.
    """
    try:
        if type(value_hex) is not str:
            return False
        raw = bytes.fromhex(value_hex)
        if len(raw) < 8:
            return False
        channel, preset_id, change, slot, algorithm, config, bypass, count = raw[:8]
        if len(raw) != 8 + count * 5 or change > 4 or bypass not in (0, 1, 255):
            return False
        expected = action["expected"]
        if (channel, preset_id, slot) != (expected["channel"], expected["preset_id"], expected["slot_id"]):
            return False
        model = MODELS[expected["model_id"]]
        definitions = _parameters(model)
        values = {}
        for offset in range(8, len(raw), 5):
            identifier = raw[offset]
            encoded = raw[offset+1:offset+5]
            number = struct.unpack("<f", encoded)[0]
            if identifier in values or identifier not in definitions or not math.isfinite(number):
                return False
            definition = definitions[identifier]
            if not definition["wire_min"] <= number <= definition["wire_max"]:
                return False
            values[identifier] = encoded.hex().upper()
        model_matches = (algorithm, config) == (model["algorithm_id"], model["config_id"])
        if action["action"] == "set_effect_parameter":
            return (change == 4 and model_matches and bypass in (expected["bypass"], 255)
                    and values == {expected["parameter_id"]: expected["value_hex"]})
        if action["action"] == "set_effect_model":
            return change in (0, expected["change"]) and model_matches
        if action["action"] == "set_effect_bypass":
            omitted_model = change == 1 and (algorithm, config) == (255, 255)
            return (change in (0, 1) and (model_matches or omitted_model)
                    and bypass == expected["bypass"])
        return False
    except (ValueError, KeyError, TypeError, struct.error):
        return False
