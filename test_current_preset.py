import math
import struct
import unittest

from current_preset import parse_preset_info, parse_selection


# Independent wire fixture: preset1, genre2, name Clean, one AMP slot using
# American Clean; Drive=25.5 and Treble=70.0, encoded IEEE754 little endian.
DETAIL = bytes.fromhex("010205436C65616E01 0306000002 000000CC41 0300008C42")


class SelectionTests(unittest.TestCase):
    def test_channel_and_unsigned_id(self):
        result = parse_selection(bytes.fromhex("03E1"))
        self.assertEqual(result["channel_label"], "CH3")
        self.assertEqual(result["preset_id"], 225)
        self.assertEqual(result["raw_hex"], "03E1")

    def test_unknown_channel_and_ff_preserved(self):
        result = parse_selection(b"\xff\xff")
        self.assertEqual((result["channel"], result["preset_id"]), (255, 255))
        self.assertIsNone(result["channel_label"])

    def test_exact_length(self):
        for raw in [b"", b"\x03", b"\x03\x01\x00"]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_selection(raw)


class PresetDetailTests(unittest.TestCase):
    def test_amp_values_and_labels(self):
        result = parse_preset_info(DETAIL)
        self.assertEqual((result["preset_id"], result["genre"], result["name"]), (1, 2, "Clean"))
        self.assertEqual(result["saved_vs_preview_semantics"], "unverified")
        slot = result["slots"][0]
        self.assertEqual(slot["slot_label"], "AMP")
        self.assertEqual(slot["algorithm_label"], "American Clean")
        self.assertIs(slot["bypass"], False)
        self.assertEqual([p["parameter_id"] for p in slot["parameters"]], [0, 3])
        self.assertEqual([p["value"] for p in slot["parameters"]], [25.5, 70.0])
        drive = slot["parameters"][0]
        self.assertEqual(drive["label"], "Drive")
        self.assertEqual(drive["ui_range"], [0, 100])
        self.assertTrue(drive["within_ui_range"])
        self.assertEqual(drive["value_hex"], "0000CC41")

    def test_all_truncated_prefixes_rejected(self):
        for length in range(len(DETAIL)):
            with self.subTest(length=length), self.assertRaises(ValueError):
                parse_preset_info(DETAIL[:length])

    def test_utf8_byte_length_and_unsigned_metadata(self):
        result = parse_preset_info(bytes.fromhex("FFFE02C3A900"))
        self.assertEqual(result["preset_id"], 255)
        self.assertEqual(result["genre"], 254)
        self.assertEqual(result["name"], "é")
        self.assertEqual(result["name_length"], 2)
        self.assertEqual(result["slots"], [])

    def test_invalid_utf8_rejected(self):
        for name in [b"\xff", b"\xc3", b"\xc0\xaf", b"\xed\xa0\x80"]:
            raw = b"\x01\x02" + bytes([len(name)]) + name + b"\x00"
            with self.subTest(name=name), self.assertRaises(ValueError):
                parse_preset_info(raw)

    def test_ff_unknown_metadata_and_unknown_parameter_preserved(self):
        raw = bytes.fromhex("01020001 FFFFFFFF01 FE000040C0")
        slot = parse_preset_info(raw)["slots"][0]
        self.assertEqual([slot[k] for k in ["slot_id", "algorithm_id", "config_id", "bypass_raw"]], [255] * 4)
        self.assertIsNone(slot["bypass"])
        self.assertIsNone(slot["algorithm_label"])
        parameter = slot["parameters"][0]
        self.assertEqual(parameter["parameter_id"], 254)
        self.assertEqual(parameter["value"], -3.0)
        self.assertIsNone(parameter["label"])
        self.assertIsNone(parameter["ui_range"])
        self.assertEqual(slot["raw_hex"], "FFFFFFFF01FE000040C0")

    def test_unknown_config_does_not_acquire_drive_label(self):
        raw = bytes.fromhex("01020001 0306FF0001 000000C841")
        slot = parse_preset_info(raw)["slots"][0]
        self.assertIsNone(slot["algorithm_label"])
        self.assertIsNone(slot["parameters"][0]["label"])

    def test_noncanonical_bypass_preserved(self):
        for bypass, expected in [(0, False), (1, True), (2, None), (255, None)]:
            raw = b"\x01\x02\x00\x01\x03\x06\x00" + bytes([bypass, 0])
            slot = parse_preset_info(raw)["slots"][0]
            self.assertEqual(slot["bypass_raw"], bypass)
            self.assertIs(slot["bypass"], expected)

    def test_nonfinite_floats_rejected_even_for_unknown_parameters(self):
        for number in [math.inf, -math.inf, math.nan]:
            raw = bytes.fromhex("01020001 FFFFFFFF01 FE") + struct.pack("<f", number)
            with self.subTest(number=number), self.assertRaisesRegex(ValueError, "non-finite"):
                parse_preset_info(raw)

    def test_finite_out_of_range_read_preserved_and_flagged(self):
        raw = bytes.fromhex("01020001 0306000001 00") + struct.pack("<f", 101)
        parameter = parse_preset_info(raw)["slots"][0]["parameters"][0]
        self.assertEqual(parameter["value"], 101)
        self.assertFalse(parameter["within_ui_range"])

    def test_wrong_counts_and_trailing_bytes_rejected(self):
        for offset, count in [(8, 0), (8, 2), (8, 255), (13, 1), (13, 3), (13, 255)]:
            raw = bytearray(DETAIL)
            raw[offset] = count
            with self.subTest(offset=offset, count=count), self.assertRaises(ValueError):
                parse_preset_info(bytes(raw))
        with self.assertRaisesRegex(ValueError, "trailing"):
            parse_preset_info(DETAIL + b"\x00")

    def test_zero_counts_and_duplicate_unknown_ids_preserved(self):
        self.assertEqual(parse_preset_info(bytes.fromhex("01020000"))["slots"], [])
        empty_slot = bytes.fromhex("FFFEFDFF00")
        result = parse_preset_info(bytes.fromhex("01020002") + empty_slot * 2)
        self.assertEqual(result["slot_count"], 2)
        self.assertEqual(len(result["slots"]), 2)
        self.assertEqual(result["slots"][0], result["slots"][1])

    def test_input_type_rejected_instead_of_implicitly_coerced(self):
        for fn in [parse_selection, parse_preset_info]:
            for value in [2, "0301", None, bytearray(b"\x03\x01")]:
                with self.subTest(fn=fn.__name__, value=value), self.assertRaises(TypeError):
                    fn(value)


if __name__ == "__main__":
    unittest.main()
