import struct
import unittest

from guitar_protocol import INVENTORY_QUERY, RX, inventory_result, parse_inventory


def packet(body, command=1, count=1, index=0, identifier=0xDD00):
    return (struct.pack("<HHBBH", identifier, command, count, index, len(body)) + body).hex().upper()


def notification(raw):
    return {"event": "notification", "uuid": RX, "hex": raw, "error": None}


QUERY = {"event": "query", "purpose": "get_preset_inventory_3440", "hex": INVENTORY_QUERY}
# Independent wire fixture: id=1, genre=2, UTF-8 name='Clean'; second id=9, genre=3, empty name.
VALUE = bytes.fromhex("010205436C65616E090300")
BODY = struct.pack("<HHH", 0, 0x3440, len(VALUE)) + VALUE


class InventoryTests(unittest.TestCase):
    def test_inventory_entry_fields(self):
        self.assertEqual(parse_inventory(VALUE), [
            {"preset_id": 1, "genre": 2, "name": "Clean"},
            {"preset_id": 9, "genre": 3, "name": ""}])

    def test_name_length_counts_utf8_bytes(self):
        self.assertEqual(parse_inventory(bytes.fromhex("070002C3A9"))[0]["name"], "é")

    def test_truncation_and_invalid_utf8(self):
        for raw in [b"\x01", b"\x01\x02\x05abc", b"\x01\x02\x01\xff"]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_inventory(raw)

    def test_complete_get(self):
        self.assertTrue(inventory_result([QUERY, notification(packet(BODY))])["preset_list_verified"])

    def test_unsolicited_old_and_forwarded_not_replies(self):
        for events in [[notification(packet(BODY)), QUERY],
                       [QUERY, notification(packet(BODY, command=3))],
                       [QUERY, notification(packet(BODY, identifier=0xDD01))]]:
            self.assertFalse(inventory_result(events)["preset_list_verified"])

    def test_split_inside_tlv_and_name(self):
        parts = [BODY[:3], BODY[3:11], BODY[11:]]
        result = inventory_result([QUERY] + [notification(packet(p, count=3, index=i)) for i, p in enumerate(parts)])
        self.assertTrue(result["preset_list_verified"])
        self.assertEqual(result["presets"][0]["name"], "Clean")

    def test_incomplete_reordered_and_duplicate_fragments_fail(self):
        first = notification(packet(BODY[:4], count=2, index=0))
        second = notification(packet(BODY[4:], count=2, index=1))
        for events in [[first], [second, first], [first, first, second], [first, notification(packet(BODY))]]:
            result = inventory_result([QUERY] + events)
            self.assertFalse(result["preset_list_verified"])
            self.assertTrue(result["inventory_errors"])

    def test_failed_status_and_wrong_feature(self):
        for body in [b"\x01\x00" + BODY[2:], BODY[:2] + b"\x47\x34" + BODY[4:]]:
            self.assertFalse(inventory_result([QUERY, notification(packet(body))])["preset_list_verified"])


if __name__ == "__main__":
    unittest.main()
