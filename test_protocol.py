import struct
import unittest

from protocol import decode_frame, summarize

RX = "65786365-6C70-6F69-6E74-2E636F6D0001"
QUERY = {"event": "query", "purpose": "get_observed_feature_000D", "hex": "00DD0100010002000D00"}
REPLY = "00DD01000100070000000D00010029"


def event(raw, **kwargs):
    return {"event": "notification", "uuid": RX, "error": None, "hex": raw, **kwargs}


class FrameTests(unittest.TestCase):
    def test_actual_device_reply(self):
        d = decode_frame(bytes.fromhex(REPLY))
        self.assertEqual(d["features"], [{"id": "0x000D", "value_hex": "29", "unsigned_byte": 41, "meaning": "unverified"}])

    def test_actual_unsolicited_frames(self):
        for packet in ["00DD0300010008000000010002000001", "00DD030001000600000002000000"]:
            self.assertEqual(decode_frame(bytes.fromhex(packet))["kind"], "unsolicited_notification")

    def test_malformed_frames_rejected(self):
        cases = [b"", b"\x00\xdd", bytes.fromhex(REPLY)[:-1], bytes.fromhex(REPLY) + b"\x00",
                 bytes.fromhex("00DD010000000000"), bytes.fromhex("00DD010001010000"),
                 bytes.fromhex("00DD01000100050000000D0001"),
                 bytes.fromhex("00DD01000100060000000D000100")]
        for raw in cases:
            with self.subTest(raw=raw.hex()), self.assertRaises(ValueError):
                decode_frame(raw)

    def test_fragmented_frames_preserved_without_interpretation(self):
        d = decode_frame(bytes.fromhex("00DD01000200010000"))
        self.assertEqual(d["features"], [])
        self.assertNotIn("status", d)

    def test_nonzero_status_not_interpreted(self):
        d = decode_frame(bytes.fromhex("00DD01000100070001000D00010029"))
        self.assertEqual(d["status"], 1)
        self.assertEqual(d["features"], [])

    def test_reply_after_query_is_verified(self):
        self.assertTrue(summarize([QUERY, event(REPLY)])["query_response_verified"])

    def test_unsolicited_frame_not_query_reply(self):
        self.assertFalse(summarize([QUERY, event(REPLY.replace("0100", "0300", 1))])["query_response_verified"])

    def test_old_reply_not_accepted(self):
        self.assertFalse(summarize([event(REPLY), QUERY])["query_response_verified"])

    def test_transport_ack_not_query_reply(self):
        self.assertFalse(summarize([QUERY, {"event": "query_transport_ack", "error": None}])["query_response_verified"])

    def test_wrong_feature_not_accepted(self):
        self.assertFalse(summarize([QUERY, event(REPLY.replace("0D00", "0100"))])["query_response_verified"])

    def test_wrong_channel_or_error_not_accepted(self):
        for overrides in [{"uuid": "OTHER"}, {"error": "not permitted"}]:
            self.assertFalse(summarize([QUERY, event(REPLY, **overrides)])["query_response_verified"])

    def test_malformed_notification_recorded(self):
        result = summarize([QUERY, event("00DD")])
        self.assertFalse(result["query_response_verified"])
        self.assertEqual(len(result["decode_errors"]), 1)

    def test_forwarded_response_not_accepted(self):
        self.assertFalse(summarize([QUERY, event(REPLY.replace("00DD", "01DD", 1))])["query_response_verified"])


if __name__ == "__main__":
    unittest.main()
