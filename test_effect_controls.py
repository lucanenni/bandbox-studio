"""Independent synthetic 3445 fixtures; no Bluetooth imports or device access."""
from copy import deepcopy
import struct
import unittest

from effect_controls import CATALOG, MODELS, match_reply, set_bypass, set_model, set_parameter


def snapshot(slot=3, algorithm=6, config=0, bypass=0, values=((0, 41), (2, 59))):
    return {"slot_id": slot, "algorithm_id": algorithm, "config_id": config,
            "bypass_raw": bypass, "parameter_count": len(values), "parameters": [
                {"parameter_id": key, "value": value,
                 "value_hex": struct.pack("<f", value).hex().upper()} for key, value in values]}


def reply(change=4, slot=3, algorithm=6, config=0, bypass=255, values=((0, 40),), channel=3, preset=1):
    return (bytes([channel, preset, change, slot, algorithm, config, bypass, len(values)])
            + b"".join(bytes([key]) + struct.pack("<f", value) for key, value in values)).hex()


class CatalogTests(unittest.TestCase):
    def test_all_models_have_one_slot_and_unique_parameters(self):
        self.assertEqual(len(MODELS), 44)
        self.assertEqual([len(s["model_ids"]) for s in CATALOG["slots"]], [2, 1, 3, 11, 12, 9, 5, 1])
        for model in MODELS.values():
            self.assertIn(model["model_id"], CATALOG["slots"][model["slot_id"]]["model_ids"])
            params = [p["parameter_id"] for p in model["parameters"]]
            self.assertEqual(len(params), len(set(params)))

    def test_unknown_ui_labels_are_retained(self):
        unnamed = [p for m in MODELS.values() for p in m["parameters"] if p["name"] is None]
        self.assertEqual(len(unnamed), 5)
        self.assertTrue(all(p["internal_type"] and p["requires_parameter_in_current_slot"] for p in unnamed))


class BuilderTests(unittest.TestCase):
    def test_singleton_drive_packet_matches_observed_wire_shape(self):
        action = set_parameter(3, 1, 3, "6:0", 0, 40, True, snapshot())
        self.assertEqual(action["value_hex"], "03010403060000010000002042")
        self.assertEqual((action["command"], action["feature"], action["response_feature"]), (2, 0x3445, 0x3445))
        self.assertTrue(action["setting_write"])
        self.assertTrue(match_reply(action, "030104030600FF010000002042"))

    def test_ratio_scaling_delay_and_shape_boundaries(self):
        comp = snapshot(1, 1, values=((1, 3.0),))
        for ui, wire in [(10, 1.0), (27, 2.7), (1000, 100.0)]:
            action = set_parameter(3, 1, 1, "1:0", 1, ui, True, comp)
            self.assertEqual(bytes.fromhex(action["value_hex"])[-4:], struct.pack("<f", wire))
        delay = snapshot(6, 20, values=((1, 430),))
        for ui in [20, 1000]:
            action = set_parameter(3, 1, 6, "20:0", 1, ui, True, delay)
            self.assertEqual(bytes.fromhex(action["value_hex"])[-4:], struct.pack("<f", ui))
        tremolo = snapshot(5, 19, values=((1, 2),))
        for ui in [0, 4]:
            set_parameter(3, 1, 5, "19:0", 1, ui, True, tremolo)
        for args in [(1, "1:0", 1, 9, comp), (6, "20:0", 1, 19, delay),
                     (5, "19:0", 1, 5, tremolo)]:
            slot, model, parameter, value, data = args
            with self.subTest(args=args), self.assertRaises(ValueError):
                set_parameter(3, 1, slot, model, parameter, value, True, data)

    def test_types_identifiers_and_missing_parameters_fail_before_packet(self):
        for value in [True, 40.0, "40", None, -1, 101]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                set_parameter(3, 1, 3, "6:0", 0, value, True, snapshot())
        for channel, preset, slot, model in [(0, 1, 3, "6:0"), (3, 255, 3, "6:0"),
                                              (True, 1, 3, "6:0"), (3, 1, 4, "6:0"),
                                              (3, 1, 3, "6:255")]:
            with self.subTest(model=model), self.assertRaises(ValueError):
                set_parameter(channel, preset, slot, model, 0, 40, True, snapshot())
        for parameter in [1, 9, True]:
            with self.subTest(parameter=parameter), self.assertRaises(ValueError):
                set_parameter(3, 1, 3, "6:0", parameter, 40, True, snapshot())
        with self.assertRaises(ValueError):
            set_parameter(3, 1, 3, "6:0", 0, 40, False, snapshot())
        with self.assertRaises(ValueError):
            set_parameter(3, 1, 3, "6:0", 0, 40, 1, snapshot())

    def test_snapshot_must_have_consistent_complete_list_and_metadata(self):
        cases = []
        for field, value in [("slot_id", 4), ("algorithm_id", 29), ("config_id", 1),
                             ("bypass_raw", 255), ("parameter_count", 1)]:
            item = snapshot(); item[field] = value; cases.append(item)
        item = snapshot(); item["parameters"].append(deepcopy(item["parameters"][0])); item["parameter_count"] = 3; cases.append(item)
        item = snapshot(); item["parameters"][0]["value_hex"] = "00002842"; cases.append(item)
        item = snapshot(); item["parameters"][0]["value"] = float("nan"); cases.append(item)
        item = snapshot(); item["parameters"][0]["parameter_id"] = 254; cases.append(item)
        for item in cases:
            with self.subTest(snapshot=item), self.assertRaises(ValueError):
                set_bypass(3, 1, 3, "6:0", False, item)

    def test_model_packets_use_app_change_codes_and_omit_values_bypass(self):
        amp = set_model(3, 1, 3, "6:0", "29:0")
        self.assertEqual(amp["value_hex"], "030103031D00FF00")
        cab = set_model(3, 1, 4, "8:2", "8:11")
        self.assertEqual(cab["value_hex"], "03010304080BFF00")
        wah = set_model(3, 1, 2, "2:0", "4:0")
        self.assertEqual(wah["value_hex"], "030102020400FF00")
        with self.assertRaises(ValueError):
            set_model(3, 1, 3, "6:0", "8:0")
        with self.assertRaises(ValueError):
            set_model(3, 1, 3, "6:0", "6:0")

    def test_bypass_preserves_parameter_order_and_raw_float_bytes(self):
        data = snapshot(values=((2, 59), (0, 41)))
        action = set_bypass(3, 1, 3, "6:0", False, data)
        self.assertEqual(action["value_hex"], "03010103060001020200006C420000002442")
        self.assertEqual(data, snapshot(values=((2, 59), (0, 41))))
        with self.assertRaises(ValueError):
            set_bypass(3, 1, 3, "6:0", True, data)
        cab = set_bypass(3, 1, 4, "8:0", False, snapshot(4, 8, values=()))
        self.assertEqual(cab["value_hex"], "0301010408000100")


class ReplyTests(unittest.TestCase):
    def setUp(self):
        self.parameter = set_parameter(3, 1, 3, "6:0", 0, 40, True, snapshot())

    def test_parameter_requires_exact_identity_type_and_target(self):
        self.assertTrue(match_reply(self.parameter, reply()))
        self.assertTrue(match_reply(self.parameter, reply(bypass=0)))
        for changes in [{"change": 0}, {"change": 1}, {"slot": 4}, {"config": 1},
                        {"algorithm": 255, "config": 255}, {"bypass": 1}, {"channel": 4},
                        {"preset": 2}, {"values": ((0, 41),)}, {"values": ((2, 40),)},
                        {"values": ((0, 40), (2, 59))}]:
            with self.subTest(changes=changes):
                self.assertFalse(match_reply(self.parameter, reply(**changes)))

    def test_model_requires_target_config_in_model_or_full_reply(self):
        action = set_model(3, 1, 3, "6:0", "6:1")
        for change in [0, 3]:
            self.assertTrue(match_reply(action, reply(change=change, config=1, values=())))
        self.assertFalse(match_reply(action, reply(change=1, config=1, values=())))
        self.assertFalse(match_reply(action, reply(change=3, config=0, values=())))

    def test_bypass_requires_concrete_boolean_and_only_proven_model_omission(self):
        action = set_bypass(3, 1, 3, "6:0", False, snapshot())
        self.assertTrue(match_reply(action, reply(change=1, bypass=1, values=())))
        self.assertTrue(match_reply(action, reply(change=1, algorithm=255, config=255, bypass=1, values=())))
        self.assertTrue(match_reply(action, reply(change=0, bypass=1, values=((0, 41),))))
        for changes in [{"bypass": 255}, {"bypass": 0}, {"change": 4, "bypass": 1},
                        {"algorithm": 255, "bypass": 1}, {"config": 1, "bypass": 1},
                        {"change": 0, "algorithm": 255, "config": 255, "bypass": 1}]:
            args = {"change": 1, "values": ()}; args.update(changes)
            with self.subTest(changes=changes):
                self.assertFalse(match_reply(action, reply(**args)))

    def test_malformed_nonfinite_duplicate_and_out_of_range_replies_fail(self):
        cases = [None, "xyz", "", reply()[:-2], reply()+"00",
                 reply(values=((0, float("nan")),)), reply(values=((0, float("inf")),)),
                 reply(values=((0, 40), (0, 40))), reply(values=((0, 101),)),
                 reply(values=((99, 40),))]
        for value in cases:
            with self.subTest(value=value):
                self.assertFalse(match_reply(self.parameter, value))


if __name__ == "__main__":
    unittest.main()
