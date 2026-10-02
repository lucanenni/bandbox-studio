import copy
import math
import unittest

from looper_controls import (
    build_bars, build_recording_start, build_recording_stop, response_matches,
)


def empty_state(**changes):
    return {"verified": True, "age_seconds": 1,
            "looper_recording_state": 0, "looper_playback": 0,
            "looper_recorded_length": 0, "looper_layer_count": 0,
            "drum_enabled": False, "metronome_enabled": False, **changes}


def bars_state(**changes):
    values = dict(mode="drum", drum_enabled=True, looper_bars=4,
                  looper_estimated_duration_ms=8000)
    values.update(changes)
    return empty_state(**values)


class LooperControlsTests(unittest.TestCase):
    def test_start_is_exactly_one_freehand_request_without_state_changes(self):
        state = empty_state()
        before = copy.deepcopy(state)
        request = build_recording_start(state)
        self.assertEqual(request, {"action": "looper_record_start", "command": 2,
            "feature": 0x3140, "value_hex": "01", "setting_write": True,
            "response_feature": 0x3140})
        self.assertEqual(state, before)
        self.assertTrue(response_matches(request, 0x3140, b"\x01"))
        for feature, raw in ((0x3145, b"\x01"), (0x3140, b"\x00"),
                             (0x3140, b""), (0x3140, b"\x01\x00")):
            self.assertFalse(response_matches(request, feature, raw))

    def test_every_required_start_read_must_be_present(self):
        for name in empty_state():
            state = empty_state()
            del state[name]
            with self.subTest(name=name), self.assertRaises(ValueError):
                build_recording_start(state)

    def test_stale_unknown_or_forged_default_state_does_not_build(self):
        for state in (None, [], {}, empty_state(verified=False), empty_state(verified=1),
                      empty_state(age_seconds=-1), empty_state(age_seconds=30.001),
                      empty_state(age_seconds=math.nan), empty_state(age_seconds=math.inf),
                      empty_state(age_seconds=True), empty_state(age_seconds="0")):
            for builder in (build_recording_start, build_recording_stop):
                with self.subTest(state=state, builder=builder), self.assertRaises(ValueError):
                    builder(state)
        self.assertEqual(build_recording_start(empty_state(age_seconds=30))["value_hex"], "01")

    def test_existing_loop_and_active_or_ambiguous_modes_block_start(self):
        changes = [{"looper_recorded_length": 1}, {"looper_layer_count": 1},
                   {"looper_layer_count": 255}, {"drum_enabled": True},
                   {"metronome_enabled": True}]
        changes += [{"looper_recording_state": op} for op in range(1, 7)]
        changes += [{"looper_playback": op} for op in range(1, 4)]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                build_recording_start(empty_state(**change))

    def test_read_types_are_strict_and_unknown_values_block(self):
        for name in ("looper_recording_state", "looper_playback",
                     "looper_recorded_length", "looper_layer_count"):
            for value in (False, 0.0, "0", None, -1, 65536):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    build_recording_start(empty_state(**{name: value}))
        for name in ("drum_enabled", "metronome_enabled"):
            for value in (0, 1, None, "false"):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    build_recording_start(empty_state(**{name: value}))

    def test_stop_requires_known_active_operation_and_never_selects_cancel(self):
        for op in (1, 2, 3):
            state = {"verified": True, "age_seconds": 0, "looper_recording_state": op}
            request = build_recording_stop(state)
            self.assertEqual((request["action"], request["feature"], request["value_hex"]),
                             ("looper_record_stop", 0x3140, "00"))
        for op in (0, 4, 5, 6, 7, 255, -1, True, "1", 1.0, None):
            with self.subTest(op=op), self.assertRaises(ValueError):
                build_recording_stop(empty_state(looper_recording_state=op))

    def test_bars_mode_choices_and_normal_descriptor(self):
        request = build_bars(8, bars_state())
        self.assertEqual(request, {"action": "looper_bars", "command": 2,
            "feature": 0x3147, "value_hex": "08", "setting_write": True,
            "response_feature": 0x3147})
        self.assertTrue(response_matches(request, 0x3147, b"\x08"))
        metronome = bars_state()
        metronome.update(mode="metronome", drum_enabled=False, metronome_enabled=True)
        for value in (1, 2):
            self.assertEqual(build_bars(value, metronome)["value_hex"], f"{value:02X}")
            with self.assertRaises(ValueError):
                build_bars(value, bars_state())

    def test_bars_cannot_touch_existing_or_recording_loop(self):
        for changes in ({"looper_recorded_length": 1000}, {"looper_layer_count": 1},
                        {"looper_recording_state": 1}, {"looper_playback": 255}):
            state = bars_state()
            state.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                build_bars(8, state)

    def test_bars_requires_matching_known_preview_and_complete_fresh_reads(self):
        for name in bars_state():
            state = bars_state()
            del state[name]
            with self.subTest(name=name), self.assertRaises(ValueError):
                build_bars(8, state)
        for changes in ({"mode": "freehand"}, {"drum_enabled": False},
                        {"metronome_enabled": True}, {"mode": "metronome"},
                        {"verified": False}, {"age_seconds": 31}):
            state = bars_state()
            state.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                build_bars(8, state)

    def test_bars_validates_duration_before_one_write_and_never_auto_adjusts(self):
        state = bars_state()
        state["looper_estimated_duration_ms"] = 30000
        self.assertEqual(build_bars(8, state)["value_hex"], "08")  # Exactly 60000ms.
        state["looper_estimated_duration_ms"] = 30004
        with self.assertRaises(ValueError):
            build_bars(8, state)
        for field, values in (("looper_bars", (0, 3, 255, True, None)),
                              ("looper_estimated_duration_ms", (0, 1, -1, True, 8000.0, 2**32))):
            for value in values:
                state = bars_state()
                state[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    build_bars(8, state)

    def test_bars_rejects_noop_wrong_types_and_unlisted_values(self):
        for value in (4, 0, 3, 5, 33, 255, -1, 8.0, True, "8", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                build_bars(value, bars_state())

    def test_matcher_rejects_ack_malformed_and_other_operation_descriptors(self):
        request = build_recording_start(empty_state())
        for changes in ({"action": "discard"}, {"command": 1}, {"setting_write": False},
                        {"value_hex": "05"}, {"value_hex": "0100"}, {"value_hex": "?"},
                        {"feature": 0x3145}, {"response_feature": 0x3145}):
            with self.subTest(changes=changes):
                self.assertFalse(response_matches(dict(request, **changes), 0x3140, b"\x01"))
        for request, feature, value in ((None, 0x3140, b"\x01"), ({}, 0x3140, b"\x01"),
                                        (request, 0x3140, "01"), (request, True, b"\x01")):
            self.assertFalse(response_matches(request, feature, value))


if __name__ == "__main__":
    unittest.main()
