import os
import tempfile
import unittest
from datetime import date, timedelta

from reservation import ReservationStore, normalize_reservation_time, parse_reservation_date
from reservation_bot import process_reservation_message


class ReservationStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = ReservationStore(os.path.join(self.temp_dir.name, "test.sqlite3"))
        self.booking_date = date.today() + timedelta(days=5)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_only_opening_hours_and_full_duration_fit(self):
        slots = self.store.get_slots(self.booking_date, 2)
        self.assertEqual(slots, ["11:30", "12:30", "17:00", "18:00"])
        self.assertNotIn("14:00", slots)
        self.assertNotIn("16:00", slots)
        self.assertNotIn("13:30", slots)
        self.assertNotIn("19:00", slots)
        self.assertFalse(self.store.is_opening_slot("13:30"))
        self.assertFalse(self.store.is_opening_slot("19:00"))
        self.assertTrue(self.store.is_opening_slot("12:30"))
        self.assertTrue(self.store.is_opening_slot("18:00"))

    def test_table_inventory_prevents_overbooking_and_cancel_releases_tables(self):
        first = self.store.create_reservation("u1", "客人甲", 36, self.booking_date, "11:30")
        self.assertEqual(len(first["table_ids"]), 12)
        self.assertEqual(self.store.get_slots(self.booking_date, 1), ["12:30", "17:00", "18:00"])
        self.assertIsNone(
            self.store.create_reservation("u2", "額外客人", 1, self.booking_date, "11:30")
        )
        self.assertIsNone(
            self.store.create_reservation("u2", "無效時段", 1, self.booking_date, "14:00")
        )
        self.assertIsNone(
            self.store.create_reservation("u2", "最後一小時", 1, self.booking_date, "19:00")
        )
        self.assertTrue(self.store.cancel_user_reservation(first["id"], "u1"))
        self.assertIn("11:30", self.store.get_slots(self.booking_date, 1))

    def test_party_size_gets_smallest_sufficient_table(self):
        booking = self.store.create_reservation("u2", "客人乙", 2, self.booking_date, "17:00")
        self.assertEqual(booking["table_ids"], ["2-1"])
        four_top = self.store.create_reservation("u3", "客人丙", 4, self.booking_date, "17:00")
        self.assertEqual(four_top["table_ids"], ["4-1"])

    def test_prevents_duplicate_booking_by_same_user_and_time(self):
        first = self.store.create_reservation("same-user", "客人甲", 2, self.booking_date, "11:30")
        self.assertIsNotNone(first)
        self.assertNotIn("11:30", self.store.available_slots(self.booking_date, 2, "same-user"))
        self.assertIsNone(
            self.store.create_reservation("same-user", "客人甲", 2, self.booking_date, "11:30")
        )

    def test_booking_state_persists_and_rejects_bad_inputs(self):
        self.store.set_state("u4", {"step": "party_size", "party_size": 3})
        self.assertEqual(self.store.get_state("u4")["party_size"], 3)
        self.assertIsNone(parse_reservation_date("2026/02/30"))
        self.assertIsNone(parse_reservation_date((date.today() + timedelta(days=91)).isoformat()))
        self.assertIsNone(normalize_reservation_time("20:30"))
        self.assertIsNone(normalize_reservation_time("13:30"))
        self.assertIsNone(normalize_reservation_time("19:00"))
        self.assertEqual(normalize_reservation_time("18:00"), "18:00")
        self.assertEqual(normalize_reservation_time("1130"), "11:30")

    def test_line_booking_prompts_and_confirms(self):
        user = "line-user"
        self.assertIn("用餐人數", process_reservation_message(self.store, user, "預約"))
        self.assertIn("整數", process_reservation_message(self.store, user, "0"))
        self.assertIn("整數", process_reservation_message(self.store, user, "9" * 5000))
        self.assertIn("日期", process_reservation_message(self.store, user, "2"))
        self.assertIn("尚可預約", process_reservation_message(self.store, user, self.booking_date.isoformat()))
        self.assertIn("最後一小時", process_reservation_message(self.store, user, "13:30"))
        self.assertIn("姓名", process_reservation_message(self.store, user, "11:30"))
        confirmation = process_reservation_message(self.store, user, "測試客人")
        self.assertIn("預約完成", confirmation)
        self.assertEqual(len(self.store.get_user_reservations(user)), 1)


if __name__ == "__main__":
    unittest.main()
