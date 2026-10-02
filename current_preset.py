"""Read-only decoders for complete JBL BandBox preset feature values.

The caller must validate/reassemble the transport and match responses to queries.
This module accepts *feature values*, without a frame, status, or TLV header.
It does not establish whether preset details represent saved or preview state.

Evidence: JBL One 2.7.9 APK V5GuitarPresetSelect, V5GuitarPresetInfo,
V5SlotItem, Algorithm, SlotValueTypeEnum, and the app's UI resource mapping.
See work/jblone-analysis/preset-review/FINDINGS.md and resources-review/README.md
in the investigation workspace. There are no command or SET builders here.
"""

import math
import struct


SELECTION_FEATURE = 0x3442
PRESET_INFO_FEATURE = 0x3444
CHANNEL_LABELS = {0: "Master", 1: "CH1", 2: "CH2", 3: "CH3", 4: "CH4"}
SLOT_LABELS = {
    0: "FX1", 1: "FX2", 2: "FX3", 3: "AMP", 4: "CAB",
    5: "MOD", 6: "DELAY", 7: "REVERB",
}
# Algorithm ID 6, configuration IDs 0..8. These are APK definitions, not an
# assertion that every definition is supported by the connected firmware.
TUBE_AMP_NAMES = {
    0: "American Clean", 1: "Jazz Sound", 2: "Yellow Tweed",
    3: "UK Crunch", 4: "British Lead", 5: "Vintage Drive",
    6: "American Gain Stack", 7: "US Metal", 8: "Bass Amp",
}
TUBE_AMP_PARAMETERS = {0: "Drive", 1: "Bass", 2: "Mid", 3: "Treble", 4: "Volume"}


def _require_bytes(value: bytes) -> None:
    if not isinstance(value, bytes):
        raise TypeError("feature value must be bytes")


def parse_selection(value: bytes) -> dict:
    """Decode feature 0x3442: channel:u8, preset ID:u8.

    Unknown channel numbers and IDs, including FF, are preserved as unsigned
    bytes; no sentinel meaning or preset-name association is inferred.
    """
    _require_bytes(value)
    if len(value) != 2:
        raise ValueError("preset selection value must contain exactly two bytes")
    channel, preset_id = value
    return {
        "feature_id": "0x3442",
        "channel": channel,
        "channel_label": CHANNEL_LABELS.get(channel),
        "preset_id": preset_id,
        "raw_hex": value.hex().upper(),
    }


def _parse_slot(value: bytes, pos: int) -> tuple[dict, int]:
    start = pos
    if len(value) - pos < 5:
        raise ValueError("truncated preset slot header")
    slot_id, algorithm_id, config_id, bypass_raw, parameter_count = value[pos:pos + 5]
    pos += 5
    if len(value) - pos < parameter_count * 5:
        raise ValueError("truncated preset slot parameters")

    known_tube_amp = algorithm_id == 6 and config_id in TUBE_AMP_NAMES
    parameters = []
    for _ in range(parameter_count):
        parameter_id = value[pos]
        encoded_float = value[pos + 1:pos + 5]
        number = struct.unpack("<f", encoded_float)[0]
        if not math.isfinite(number):
            raise ValueError("non-finite preset parameter value")
        label = TUBE_AMP_PARAMETERS.get(parameter_id) if known_tube_amp else None
        parameters.append({
            "parameter_id": parameter_id,
            "label": label,
            "value": number,
            "value_hex": encoded_float.hex().upper(),
            "raw_hex": value[pos:pos + 5].hex().upper(),
            # The amp UI casts integers directly to floats; it does not divide
            # them by 100. Out-of-range finite read values remain visible.
            "ui_range": [0, 100] if label is not None else None,
            "within_ui_range": 0 <= number <= 100 if label is not None else None,
            "semantic_source": "JBL One 2.7.9 APK" if label is not None else None,
        })
        pos += 5

    return {
        "slot_id": slot_id,
        "slot_label": SLOT_LABELS.get(slot_id),
        "algorithm_id": algorithm_id,
        "config_id": config_id,
        "algorithm_label": TUBE_AMP_NAMES[config_id] if known_tube_amp else None,
        "bypass_raw": bypass_raw,
        # Preserve FF and any noncanonical byte rather than assigning meaning
        # to an absent/unknown field or coercing every other byte to false.
        "bypass": {0: False, 1: True}.get(bypass_raw),
        "parameter_count": parameter_count,
        "parameters": parameters,
        "raw_hex": value[start:pos].hex().upper(),
    }, pos


def parse_preset_info(value: bytes) -> dict:
    """Decode feature 0x3444 with exact lengths, UTF-8, and finite float32s.

    IDs are unsigned bytes. Unknown metadata, duplicate IDs, and zero counts
    are retained in ordered lists instead of discarded or guessed. Counts
    must consume the complete value exactly; trailing bytes are an error.
    """
    _require_bytes(value)
    if len(value) < 4:
        raise ValueError("truncated preset detail header")
    preset_id, genre, name_length = value[:3]
    pos = 3 + name_length
    if pos >= len(value):
        raise ValueError("truncated preset name or missing slot count")
    name_bytes = value[3:pos]
    try:
        name = name_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("invalid UTF-8 preset name") from exc
    slot_count = value[pos]
    pos += 1
    if len(value) - pos < slot_count * 5:
        raise ValueError("truncated preset slots")
    slots = []
    for _ in range(slot_count):
        slot, pos = _parse_slot(value, pos)
        slots.append(slot)
    if pos != len(value):
        raise ValueError("unexpected trailing bytes after preset slots")
    return {
        "feature_id": "0x3444",
        "preset_id": preset_id,
        "genre": genre,
        "name": name,
        "name_length": name_length,
        "name_hex": name_bytes.hex().upper(),
        "slot_count": slot_count,
        "slots": slots,
        "raw_hex": value.hex().upper(),
        "saved_vs_preview_semantics": "unverified",
    }
