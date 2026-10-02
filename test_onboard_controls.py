import math
import struct
import unittest
from decimal import Decimal

from onboard_controls import (
    READABLE_CONTROLS, SETTABLE_CONTROLS, build_read, build_set,
    decode_response, response_matches, describe_controls,
)


class OnboardControlsTests(unittest.TestCase):
    def test_reads_use_get_except_explicit_parameterized_queries(self):
        for name, feature in (("drum_bpm", 0x3001), ("tuner_reference_hz", 0x3103),
                              ("looper_layer_count", 0x3148), ("supported_features", 0x3805)):
            with self.subTest(name=name):
                self.assertEqual(build_read(name), {"action": f"read_{name}", "command": 1,
                    "feature": feature, "setting_write": False, "response_feature": feature})

    def test_parameterized_queries_do_not_change_settings(self):
        cases = [
            (build_read("master_volume"), 0x3405, 0x3406, "0000"),
            (build_read("channel_volume", channel=3, input_type="guitar"), 0x3405, 0x3406, "0302"),
            (build_read("channel_input", channel=2), 0x3400, 0x3401, "02"),
            (build_read("page_in_use", page="looper"), 0x3803, 0x3804, "02"),
        ]
        for request, feature, response, encoded in cases:
            with self.subTest(feature=feature, encoded=encoded):
                self.assertEqual((request["command"], request["feature"], request["response_feature"],
                                  request["value_hex"], request["setting_write"]),
                                 (2, feature, response, encoded, False))

    def test_read_scopes_are_not_silently_ignored(self):
        for kwargs in ({"control": "drum_bpm", "channel": 1},
                       {"control": "master_volume", "input_type": "guitar"},
                       {"control": "channel_volume", "channel": True, "input_type": "guitar"},
                       {"control": "channel_input", "channel": 0},
                       {"control": "channel_input", "channel": 1, "input_type": "mic"},
                       {"control": "channel_volume", "channel": 3},
                       {"control": "page_in_use", "page": "all"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                build_read(**kwargs)

    def test_bpm_bounds_unsigned_encoding_and_rejecting_bool(self):
        self.assertEqual(build_set("drum_bpm", 240)["value_hex"], "F0")
        self.assertEqual(build_set("metronome_bpm", 30)["value_hex"], "1E")
        for value in (29, 241, -1, 256, 120.0, True, "120"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                build_set("drum_bpm", value)

    def test_pattern_wire_ids_are_not_enum_ordinals(self):
        self.assertEqual(build_set("drum_pattern", "blues_1")["value_hex"], "04")
        self.assertEqual(build_set("drum_pattern", "jazz")["value_hex"], "0F")
        self.assertEqual(build_set("metronome_meter", "6/8")["value_hex"], "03")
        self.assertEqual(build_set("tuner_tuning", "bass_bead")["value_hex"], "20")
        self.assertEqual(build_set("tuner_tuning", "ukulele_canadian")["value_hex"], "1C")
        for value in (0, 4, "4", "unknown"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                build_set("drum_pattern", value)

    def test_tuner_reference_is_tenths_hz_little_endian(self):
        self.assertEqual(build_set("tuner_reference_hz", 440)["value_hex"], "3011")
        self.assertEqual(build_set("tuner_reference_hz", 440.1)["value_hex"], "3111")
        self.assertEqual(build_set("tuner_reference_hz", Decimal("420.0"))["value_hex"], "6810")
        self.assertEqual(build_set("tuner_reference_hz", 460)["value_hex"], "F811")
        result = decode_response(0x3103, b"\x31\x11")
        self.assertEqual((result["value"], result["raw_value"], result["unit"]), (440.1, 4401, "Hz"))

    def test_tuner_reference_rejects_wrong_scale_precision_and_nonfinite(self):
        for value in (4400, 419.9, 460.1, 440.01, True, "440", math.inf, math.nan, Decimal("sNaN")):
            with self.subTest(value=str(value)), self.assertRaises(ValueError):
                build_set("tuner_reference_hz", value)

    def test_bool_setters_require_bool_and_decoders_canonical_bytes(self):
        request = build_set("tuner_enabled", True)
        self.assertEqual((request["feature"], request["value_hex"], request["setting_write"]), (0x3100, "01", True))
        self.assertIs(decode_response(0x3100, b"\x01")["value"], True)
        for value in (1, 0, "true", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                build_set("tuner_enabled", value)
        with self.assertRaises(ValueError):
            decode_response(0x3100, b"\x02")

    def test_looper_playback_exposes_only_nondiscard_operations(self):
        for name, wire in (("stop", "00"), ("play", "01"), ("pause", "02"), ("resume", "03")):
            with self.subTest(name=name):
                request = build_set("looper_playback", name)
                self.assertEqual((request["feature"], request["value_hex"]), (0x3145, wire))
        for name in ("discard", "undo", "cancel", "record", "start_first"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                build_set("looper_playback", name)

    def test_unproven_and_destructive_writes_cannot_be_built(self):
        for name in ("looper_recording_state", "looper_bars", "master_volume", "channel_volume",
                     "page_in_use", "factory_reset", "firmware", "raw", "looper_clear",
                     "looper_recorded_length", "supported_features", "drum_tap"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                build_set(name, 1)
        self.assertNotIn("looper_recording_state", SETTABLE_CONTROLS)
        self.assertIn("looper_recording_state", READABLE_CONTROLS)

    def test_push_only_measurements_are_decodable_but_not_gettable(self):
        for name in ("tuner_result", "looper_music_signal", "looper_countdown", "drum_tap"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                build_read(name)
        tuner = decode_response(0x3106, struct.pack("<fBfB", 440.5, 2, -12.5, 1))
        self.assertEqual((tuner["frequency"], tuner["tuner_mode"], tuner["result"], tuner["has_signal"]),
                         (440.5, 2, -12.5, True))
        self.assertEqual(tuner["result_unit"], "not_verified")
        self.assertEqual(decode_response(0x3142, struct.pack("<f", 0.25))["value"], 0.25)
        self.assertEqual(decode_response(0x3003, b"")["event"], "drum_tap")

    def test_supported_features_have_no_count_prefix_and_preserve_unknowns(self):
        decoded = decode_response(0x3805, bytes([2, 10, 255, 2]))
        self.assertEqual(decoded["capabilities"], [
            {"id": 2, "name": "drum"}, {"id": 10, "name": "looper"},
            {"id": 255, "name": None}, {"id": 2, "name": "drum"},
        ])
        self.assertEqual(decode_response(0x3805, b"")["capabilities"], [])

    def test_unknown_enum_and_out_of_ui_range_reads_remain_visible(self):
        self.assertEqual(decode_response(0x3002, b"\xFE")["name"], None)
        bpm = decode_response(0x3001, b"\xFF")
        self.assertEqual(bpm["value"], 255)
        self.assertFalse(bpm["within_ui_range"])
        volume = decode_response(0x3406, b"\x00\x00\xC8")
        self.assertEqual((volume["value"], volume["unit"]), (200, "not_verified"))

    def test_unsigned_time_fields_and_explicit_unit_limits(self):
        self.assertEqual(decode_response(0x314A, b"\xFF\xFF\xFF\xFF")["value"], 4294967295)
        self.assertEqual(decode_response(0x3146, b"\xFF\xFF")["value"], 65535)
        length = decode_response(0x3143, b"\xE8\x03")
        self.assertEqual((length["value"], length["unit"]), (1000, "ms"))
        self.assertEqual(describe_controls()["readable_controls"]["looper_recorded_length"]["value_description"]["unit"], "ms")
        self.assertEqual(decode_response(0x3141, b"\x01\x00")["unit"], "not_verified")
        self.assertEqual(decode_response(0x3149, b"\xE8\x03")["unit"], "ms")

    def test_strict_lengths_trailing_bytes_and_nonfinite_measurements(self):
        shapes = ((0x3000, 1), (0x3103, 2), (0x3106, 10), (0x314A, 4),
                  (0x3401, 3), (0x3406, 3), (0x3804, 2), (0x3142, 4))
        for feature, length in shapes:
            for bad_length in (length - 1, length + 1):
                with self.subTest(feature=feature, length=bad_length), self.assertRaises(ValueError):
                    decode_response(feature, bytes(bad_length))
        for feature, payload in ((0x3106, struct.pack("<fBfB", math.nan, 0, 0, 1)),
                                 (0x3106, struct.pack("<fBfB", 440, 0, math.inf, 1)),
                                 (0x3142, struct.pack("<f", math.nan))):
            with self.subTest(feature=feature), self.assertRaises(ValueError):
                decode_response(feature, payload)

    def test_set_match_requires_correct_feature_and_exact_value(self):
        request = build_set("drum_bpm", 120)
        self.assertTrue(response_matches(request, 0x3001, b"\x78"))
        self.assertFalse(response_matches(request, 0x3041, b"\x78"))
        self.assertFalse(response_matches(request, 0x3001, b"\x77"))
        self.assertFalse(response_matches(request, 0x3001, b""))  # ACK is not a state value.
        self.assertFalse(response_matches(request, 0x3001, b"\x78\x00"))

    def test_read_match_requires_requested_scope(self):
        cases = [
            (build_read("master_volume"), 0x3406, b"\x00\x00\x29", b"\x03\x02\x29"),
            (build_read("channel_volume", channel=3, input_type="guitar"), 0x3406, b"\x03\x02\x29", b"\x03\x01\x29"),
            (build_read("channel_input", channel=2), 0x3401, b"\x02\x01\x01", b"\x01\x01\x01"),
            (build_read("page_in_use", page="tuner"), 0x3804, b"\x01\x02", b"\x02\x02"),
        ]
        for request, feature, correct, wrong in cases:
            with self.subTest(action=request["action"]):
                self.assertTrue(response_matches(request, feature, correct))
                self.assertFalse(response_matches(request, feature, wrong))

    def test_bad_request_and_bad_response_types_do_not_verify(self):
        self.assertFalse(response_matches({}, 0x3001, b"\x78"))
        self.assertFalse(response_matches(build_read("drum_bpm"), 0x3001, "78"))
        self.assertFalse(response_matches(build_read("drum_bpm"), 0x3041, b"\x78"))
        with self.assertRaises(ValueError):
            decode_response(0xFFFF, b"\x00")
        with self.assertRaises(TypeError):
            decode_response(True, b"\x00")


if __name__ == "__main__":
    unittest.main()
