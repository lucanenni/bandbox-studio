import json
import unittest

from mixer_controls import build_set, decode_volume, describe_controls, response_matches


class MixerControlsTests(unittest.TestCase):
    def test_master_uses_fixed_scope_and_raw_step_value(self):
        self.assertEqual(build_set("master_volume", 15, current_volume=b"\x00\x00\x10"), {
            "action": "set_master_volume", "command": 2, "feature": 0x3406,
            "value_hex": "00000F", "setting_write": True, "response_feature": 0x3406,
        })

    def test_channel_takes_input_scope_from_matching_input_response(self):
        for channel, kind in ((1, 1), (1, 2), (2, 1), (2, 3), (3, 2), (4, 4)):
            with self.subTest(channel=channel, kind=kind):
                req = build_set("channel_volume", 32, channel=channel,
                                input_status=bytes([channel, 1, kind]), current_volume=bytes([channel, kind, 16]))
                self.assertEqual(req["value_hex"], bytes([channel, kind, 32]).hex().upper())

    def test_source_bounds_are_steps_not_percentages(self):
        for value in (0, 32):
            self.assertEqual(build_set("master_volume", value, current_volume=b"\0\0\x10")["value_hex"], bytes([0, 0, value]).hex().upper())
        for value in (-1, 33, 47, 100, 255, 16.0, True, "16"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                build_set("master_volume", value, current_volume=b"\0\0\x10")

    def test_unknown_current_scale_blocks_even_lower_target(self):
        with self.assertRaisesRegex(ValueError, "firmware scale"):
            build_set("master_volume", 15, current_volume=b"\0\0\x2F")
        with self.assertRaisesRegex(ValueError, "firmware scale"):
            build_set("channel_volume", 15, channel=3, input_status=b"\3\1\2", current_volume=b"\3\2\x64")
        self.assertEqual(decode_volume(b"\0\0\x2F")["value"], 47)
        self.assertFalse(decode_volume(b"\0\0\x2F")["within_ui_range"])

    def test_wrong_master_scope_is_rejected(self):
        for baseline in (b"\3\2\x10", b"\0\2\x10"):
            with self.subTest(baseline=baseline), self.assertRaises(ValueError):
                build_set("master_volume", 15, current_volume=baseline)
        with self.assertRaises(ValueError):
            build_set("master_volume", 15, channel=0, current_volume=b"\0\0\x10")

    def test_changed_channel_input_between_reads_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "volume response"):
            build_set("channel_volume", 15, channel=1, input_status=b"\1\1\2", current_volume=b"\1\1\x10")
        with self.assertRaisesRegex(ValueError, "input response"):
            build_set("channel_volume", 15, channel=1, input_status=b"\2\1\1", current_volume=b"\1\1\x10")

    def test_unplugged_unknown_and_unproven_input_pairings_block(self):
        for status in (b"\3\0\2", b"\3\1\0", b"\3\1\1", b"\3\1\xFF"):
            with self.subTest(status=status), self.assertRaises(ValueError):
                build_set("channel_volume", 15, channel=3, input_status=status, current_volume=b"\3\2\x10")

    def test_missing_malformed_and_noncanonical_evidence_blocks(self):
        for status in (None, b"", b"\3\1", b"\3\1\2\0", b"\3\2\2"):
            with self.subTest(status=status), self.assertRaises((TypeError, ValueError)):
                build_set("channel_volume", 15, channel=3, input_status=status, current_volume=b"\3\2\x10")
        for baseline in (None, b"", b"\0\0", b"\0\0\x10\0", "000010"):
            with self.subTest(baseline=baseline), self.assertRaises((TypeError, ValueError)):
                build_set("master_volume", 15, current_volume=baseline)

    def test_unknown_controls_and_invalid_channels_cannot_build(self):
        for name in ("raw", "music_volume", "preset_volume", "amp_volume", "channel_input"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                build_set(name, 15, current_volume=b"\0\0\x10")
        for channel in (0, 5, True, "3", 3.0):
            with self.subTest(channel=channel), self.assertRaises(ValueError):
                build_set("channel_volume", 15, channel=channel, input_status=b"\3\1\2", current_volume=b"\3\2\x10")

    def test_match_requires_exact_value_scope_feature_and_full_state(self):
        req = build_set("channel_volume", 15, channel=3, input_status=b"\3\1\2", current_volume=b"\3\2\x10")
        self.assertTrue(response_matches(req, 0x3406, b"\3\2\x0F"))
        for feature, value in ((0x3406, b"\3\2\x10"), (0x3406, b"\1\2\x0F"),
                               (0x3406, b"\3\1\x0F"), (0x2D42, b"\x0F"),
                               (0x3406, b""), (0x3406, b"\3\2\x0F\0")):
            with self.subTest(feature=feature, value=value):
                self.assertFalse(response_matches(req, feature, value))

    def test_invalid_request_or_response_does_not_verify(self):
        self.assertFalse(response_matches({}, 0x3406, b"\0\0\x10"))
        req = build_set("master_volume", 16, current_volume=b"\0\0\x10")
        for override in ({"command": 1}, {"feature": 0x2D42}, {"setting_write": False},
                         {"action": "raw"}, {"value_hex": "not hex"}):
            self.assertFalse(response_matches({**req, **override}, 0x3406, b"\0\0\x10"))
        self.assertFalse(response_matches(req, 0x3406, "000010"))

    def test_catalog_explicitly_excludes_percentage_semantics(self):
        catalog = describe_controls()
        json.dumps(catalog)
        for info in catalog["settable_controls"].values():
            self.assertEqual((info["value"]["minimum"], info["value"]["maximum"]), (0, 32))
            self.assertFalse(info["value"]["percentage"])


if __name__ == "__main__":
    unittest.main()
