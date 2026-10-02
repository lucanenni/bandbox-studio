import math
import unittest

from preset_controls import (duplicate, parse_operation_response, rename, save_as,
                             save_user_preset, select)


class PresetBuilderTests(unittest.TestCase):
    def test_exact_select_fixture(self):
        self.assertEqual(select(3, 1), {"action": "select", "command": 2,
            "feature": 0x3442, "value_hex": "0301", "setting_write": True,
            "response_feature": 0x3442})

    def test_exact_operation_fixtures(self):
        self.assertEqual(duplicate(3, 1, "Test", 2)["value_hex"], "030101FF020454657374")
        self.assertEqual(save_as(1, 51, "Test", 2)["value_hex"], "010933FF020454657374")
        self.assertEqual(rename(3, 51, "Test")["value_hex"], "030333FFFF0454657374")
        self.assertEqual(save_user_preset(3, 51)["value_hex"], "030433FFFF00")
        for descriptor in (duplicate(3, 1, "Test", 2), save_as(3, 1, "Test", 2),
                           rename(3, 51, "Test"), save_user_preset(3, 51)):
            self.assertEqual(descriptor["feature"], 0x3446)
            self.assertEqual(descriptor["response_feature"], 0x3446)
            self.assertEqual(descriptor["command"], 2)
            self.assertIs(descriptor["setting_write"], True)

    def test_names_use_utf8_length_and_preserve_text(self):
        self.assertEqual(rename(3, 51, " é ")["value_hex"], "030333FFFF0420C3A920")
        self.assertEqual(bytes.fromhex(rename(3, 51, "é" * 127 + "x")["value_hex"])[5], 255)

    def test_invalid_names(self):
        for name in ("", " \t\n", "x" * 256, "é" * 128, "\ud800", None, 42):
            for builder in (lambda: rename(3, 51, name),
                            lambda: duplicate(3, 1, name, 1),
                            lambda: save_as(3, 1, name, 1)):
                with self.subTest(name=repr(name)), self.assertRaises(ValueError):
                    builder()

    def test_strict_ids_and_channel(self):
        bad = (-1, 255, 256, 1.0, math.inf, math.nan, True, "1", None)
        for value in bad:
            for builder in (lambda: select(3, value), lambda: duplicate(3, value, "A", 1),
                            lambda: duplicate(3, 1, "A", value),
                            lambda: save_user_preset(3, value)):
                with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                    builder()
        for value in (0, 2, 4, 255, 1.0, True, "3", None):
            with self.subTest(channel=value), self.assertRaises(ValueError):
                select(value, 1)
        self.assertEqual(select(1, 254)["value_hex"], "01FE")

    def test_factory_save_is_blocked(self):
        for preset_id in (0, 1, 27, 50):
            with self.subTest(preset_id=preset_id), self.assertRaises(ValueError):
                save_user_preset(3, preset_id)
        self.assertEqual(save_user_preset(3, 254)["value_hex"], "0304FEFFFF00")


class PresetResponseTests(unittest.TestCase):
    def setUp(self):
        self.expected = duplicate(3, 1, "Test", 2)
        self.reply = bytes.fromhex("03010133020454657374")

    def test_creation_matches_and_returns_allocated_id(self):
        self.assertEqual(parse_operation_response(self.reply, self.expected, [1, 2]),
            {"action": "duplicate", "channel": 3, "operation": 1, "source_id": 1,
             "new_preset_id": 51, "genre": 2, "name": "Test"})
        self.assertEqual(parse_operation_response("030901FE020454657374",
            save_as(3, 1, "Test", 2))["new_preset_id"], 254)

    def test_observed_duplicate_omits_source_but_keeps_request_identity_separate(self):
        # The Trio can omit the source ID while retaining the assigned ID and name.
        request = duplicate(3, 1, "Gilmour Lead", 0)
        report = parse_operation_response("0301FF33000C47696C6D6F7572204C656164",
                                          request, range(1, 28))
        self.assertIsNone(report["source_id"])
        self.assertEqual(report["requested_source_id"], 1)
        self.assertEqual(report["new_preset_id"], 51)
        self.assertEqual(report["name"], "Gilmour Lead")
        report = parse_operation_response("0309FF33020454657374",
                                          save_as(3, 1, "Test", 2), [1, 2])
        self.assertIsNone(report["source_id"])
        self.assertEqual(report["requested_source_id"], 1)

    def test_omitted_creation_source_requires_binding_prior_inventory(self):
        reply = bytes.fromhex("0301FF33020454657374")
        for prior in (None, [], [2], [1, 51]):
            with self.subTest(prior=prior), self.assertRaises(ValueError):
                parse_operation_response(reply, self.expected, prior)
        for new_id in (1, 255):
            with self.subTest(new_id=new_id), self.assertRaises(ValueError):
                parse_operation_response(reply[:3] + bytes([new_id]) + reply[4:], self.expected, [1])

    def test_omitted_source_never_allowed_for_save_or_rename(self):
        for reply, request in (("0304FFFFFF00", save_user_preset(3, 51)),
                               ("0303FFFFFF0454657374", rename(3, 51, "Test"))):
            with self.subTest(request=request), self.assertRaises(ValueError):
                parse_operation_response(reply, request, [51])

    def test_source_omission_does_not_relax_other_creation_matches(self):
        for index, value in ((0, 1), (1, 9), (4, 3), (6, ord("B"))):
            reply = bytearray.fromhex("0301FF33020454657374")
            reply[index] = value
            with self.subTest(index=index), self.assertRaises(ValueError):
                parse_operation_response(bytes(reply), self.expected, [1])
        with self.assertRaises(ValueError):
            parse_operation_response("03010233020454657374", self.expected, [1, 2])

    def test_save_and_rename_matching_reports(self):
        self.assertEqual(parse_operation_response("030433FFFF00",
            save_user_preset(3, 51))["source_id"], 51)
        self.assertEqual(parse_operation_response("030333FFFF02C3A9",
            rename(3, 51, "é"))["name"], "é")

    def test_rejects_other_channel_operation_source_genre_and_name(self):
        for index, value in ((0, 1), (1, 9), (2, 2), (4, 3), (6, ord("B"))):
            reply = bytearray(self.reply)
            reply[index] = value
            with self.subTest(index=index), self.assertRaises(ValueError):
                parse_operation_response(bytes(reply), self.expected)

    def test_rejects_missing_same_and_existing_destination(self):
        for new_id in (255, 1):
            reply = self.reply[:3] + bytes([new_id]) + self.reply[4:]
            with self.subTest(new_id=new_id), self.assertRaises(ValueError):
                parse_operation_response(reply, self.expected)
        with self.assertRaises(ValueError):
            parse_operation_response(self.reply, self.expected, [1, 51])

    def test_rejects_truncated_extra_invalid_utf8_and_wrong_input(self):
        for reply in (self.reply[:5], self.reply[:-1], self.reply + b"x",
                      self.reply[:6] + b"\xffest", "xyz", None):
            with self.subTest(reply=reply), self.assertRaises(ValueError):
                parse_operation_response(reply, self.expected)

    def test_rejects_tampered_descriptor_and_destructive_actions(self):
        for key, value in (("command", 1), ("feature", 0x3442), ("response_feature", 0x3442),
                           ("setting_write", False), ("action", "save_as"),
                           ("action", "delete"), ("value_hex", "03010133020454657374")):
            expected = {**self.expected, key: value}
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                parse_operation_response(self.reply, expected)
        with self.assertRaises(ValueError):
            parse_operation_response(self.reply, select(3, 1))

    def test_rejects_invalid_prior_inventory(self):
        with self.assertRaises(ValueError):
            parse_operation_response(self.reply, self.expected, [math.nan])


if __name__ == "__main__":
    unittest.main()
