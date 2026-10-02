import struct
import unittest

from exchange_protocol import RX, packet_for, parse_exchange
from preset_controls import select


REQUEST = select(3, 1)
GET = {"action": "read_names", "command": 1, "feature": 0x3440,
       "value_hex": "", "setting_write": False, "response_feature": 0x3440}
CONNECTED = {"event": "connected", "id": "fixture-device"}


def sent(request=REQUEST):
    return {"event": "control_send", "action": request["action"],
            "hex": packet_for(request).hex().upper(), "setting_write": request["setting_write"]}


def complete(writes=1):
    return {"event": "complete", "setting_writes": writes, "connected": True}


def notification(payload, command=3, count=1, index=0, identifier=0xDD00):
    raw = struct.pack("<HHBBH", identifier, command, count, index, len(payload)) + payload
    return {"event": "notification", "uuid": RX, "hex": raw.hex(), "error": None}


ACK = notification(b"\x00\x00", command=2)
VALUE = bytes.fromhex("0000423402000301")
REPORT = notification(VALUE)


class PacketTests(unittest.TestCase):
    def test_packet_fixtures(self):
        self.assertEqual(packet_for(REQUEST).hex().upper(), "00DD020001000600423402000301")
        self.assertEqual(packet_for(GET).hex().upper(), "00DD0100010002004034")

    def test_invalid_descriptors_are_rejected(self):
        for key, value in (("command", True), ("command", 3), ("feature", -1),
                           ("feature", 65536), ("feature", 1.0), ("action", ""),
                           ("response_feature", None), ("setting_write", 1),
                           ("value_hex", "z"), ("value_hex", "00" * 8189)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                packet_for({**REQUEST, key: value})
        for request in ({**GET, "value_hex": "01"}, {**GET, "setting_write": True}):
            with self.assertRaises(ValueError):
                packet_for(request)


class ExchangeTests(unittest.TestCase):
    def exchange(self, middle, request=REQUEST, writes=1):
        return parse_exchange([CONNECTED, sent(request), *middle, complete(writes)], request)

    def test_ack_and_value_are_distinct(self):
        result = self.exchange([ACK, REPORT])
        self.assertEqual(result, {"sent": True, "acknowledged": True,
            "feature_values": [{"feature": 0x3442, "value_hex": "0301"}],
            "errors": [], "setting_writes": 1, "connected": True})
        result = self.exchange([ACK])
        self.assertTrue(result["acknowledged"])
        self.assertEqual(result["feature_values"], [])

    def test_os_ack_cannot_substitute_protocol_ack(self):
        result = self.exchange([{"event": "query_transport_ack", "error": None}, REPORT])
        self.assertFalse(result["acknowledged"])
        self.assertTrue(result["errors"])
        self.assertEqual(result["setting_writes"], 1)

    def test_get_has_no_protocol_ack_requirement(self):
        result = self.exchange([notification(bytes.fromhex("000040340000"), command=1)], GET, 0)
        self.assertEqual(result["errors"], [])
        self.assertFalse(result["acknowledged"])
        self.assertEqual(result["feature_values"], [{"feature": 0x3440, "value_hex": ""}])

    def test_status_and_tlv_can_split_at_any_boundary(self):
        for split in range(1, len(VALUE)):
            with self.subTest(split=split):
                result = self.exchange([notification(VALUE[:split], count=2), ACK,
                                        notification(VALUE[split:], count=2, index=1)])
                self.assertEqual(result["errors"], [])
                self.assertEqual(result["feature_values"][0]["value_hex"], "0301")

    def test_fragmented_ack_is_reassembled(self):
        result = self.exchange([notification(b"\x00", command=2, count=2),
                                notification(b"\x00", command=2, count=2, index=1), REPORT])
        self.assertTrue(result["acknowledged"])

    def test_stale_responses_and_stale_initial_fragment_are_ignored(self):
        result = parse_exchange([CONNECTED, ACK, REPORT, sent(), complete()], REQUEST)
        self.assertFalse(result["acknowledged"])
        self.assertEqual(result["feature_values"], [])
        result = parse_exchange([CONNECTED, notification(VALUE[:1], count=2), sent(), ACK,
            notification(VALUE[1:], count=2, index=1), complete()], REQUEST)
        self.assertTrue(result["errors"])

    def test_wrong_request_action_or_packet_cannot_open_reply_window(self):
        for change in ({"action": "wrong"}, {"hex": packet_for(select(3, 2)).hex()}):
            result = parse_exchange([CONNECTED, {**sent(), **change}, ACK, REPORT, complete()], REQUEST)
            self.assertFalse(result["sent"])
            self.assertFalse(result["acknowledged"])
            self.assertEqual(result["setting_writes"], 1)

    def test_repeated_send_is_rejected_and_actual_write_count_preserved(self):
        result = parse_exchange([CONNECTED, sent(), ACK, sent(), REPORT, complete(2)], REQUEST)
        self.assertTrue(result["errors"])
        self.assertFalse(result["acknowledged"])
        self.assertEqual(result["setting_writes"], 2)

    def test_forwarded_reordered_duplicate_missing_and_mixed_fragments(self):
        first = notification(VALUE[:3], count=2)
        second = notification(VALUE[3:], count=2, index=1)
        for frames in ([notification(VALUE, identifier=0xDD01)], [second, first], [first, first, second],
                       [first], [first, REPORT], [first, notification(VALUE[3:], command=1, count=2, index=1)]):
            with self.subTest(frames=frames):
                result = self.exchange([ACK, *frames])
                self.assertTrue(result["errors"])
                self.assertEqual(result["feature_values"], [])

    def test_nonzero_malformed_ack_status_and_tlv_are_rejected(self):
        for frame in (notification(b"\x01\x00", command=2), notification(b"\x00", command=2),
                      notification(b"\x00\x00\x00", command=2), notification(b"\x01\x00", command=3),
                      notification(b"\x00\x00\x42", command=3),
                      notification(bytes.fromhex("0000423403000301"))):
            with self.subTest(frame=frame):
                self.assertTrue(self.exchange([ACK, frame])["errors"])

    def test_fragment_and_aggregate_size_limits(self):
        for frames in ([notification(b"", count=33)], [notification(b"\x00" * 8193)],
                       [notification(b"\x00" * 4097, count=2), notification(b"\x00" * 4096, count=2, index=1)]):
            with self.subTest(frames=len(frames)):
                self.assertTrue(self.exchange([ACK, *frames])["errors"])

    def test_gatt_error_disconnect_and_notification_error_keep_attempted_write(self):
        for failure in ({"event": "query_transport_ack", "error": "failed"},
                        {"event": "disconnected", "error": None},
                        {"event": "notification", "uuid": RX, "hex": "", "error": "read failed"}):
            with self.subTest(failure=failure):
                result = self.exchange([ACK, REPORT, failure])
                self.assertTrue(result["errors"])
                self.assertEqual(result["setting_writes"], 1)
                self.assertEqual(result["feature_values"], [])

    def test_malformed_or_contradictory_write_accounting_is_unknown(self):
        for events in ([{**sent(), "setting_write": None}, complete()],
                       [{**sent(), "hex": "bad"}, complete()], [sent(), complete(0)],
                       [sent(), {"event": "complete"}], [sent(), None, complete()]):
            with self.subTest(events=events):
                result = parse_exchange(events, REQUEST)
                self.assertIsNone(result["setting_writes"])
                self.assertTrue(result["errors"])

    def test_no_dispatch_is_zero_and_incomplete_logs_do_not_verify(self):
        result = parse_exchange([{"event": "connection_failed", "error": "timeout"}, complete(0)], REQUEST)
        self.assertEqual(result["setting_writes"], 0)
        self.assertFalse(result["connected"])
        result = parse_exchange([CONNECTED, sent(), ACK, REPORT], REQUEST)
        self.assertTrue(result["errors"])
        self.assertEqual(result["setting_writes"], 1)

    def test_wrong_characteristic_does_not_supply_value(self):
        result = self.exchange([ACK, {**REPORT, "uuid": "other"}])
        self.assertEqual(result["feature_values"], [])
        self.assertEqual(result["errors"], [])

    def test_missing_connection_or_malformed_event_cannot_verify(self):
        result = parse_exchange([sent(), ACK, REPORT, complete()], REQUEST)
        self.assertTrue(result["errors"])
        self.assertEqual(result["setting_writes"], 1)
        for event in ({}, {"event": "notification_state", "uuid": None},
                      {**REPORT, "uuid": None}):
            with self.subTest(event=event):
                self.assertTrue(self.exchange([ACK, REPORT, event])["errors"])
        self.assertIsNone(self.exchange([{}])["setting_writes"])


if __name__ == "__main__":
    unittest.main()
