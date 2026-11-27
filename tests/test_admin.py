import os
import tempfile
import unittest
from datetime import date, timedelta

import app as application
from reservation import ReservationStore


class AdminDashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_store = application.reservation_store
        application.reservation_store = ReservationStore(
            os.path.join(self.temp_dir.name, "admin-test.sqlite3")
        )
        self.client = application.app.test_client()

    def tearDown(self):
        application.reservation_store = self.original_store
        self.temp_dir.cleanup()

    def login(self):
        return self.client.post(
            "/admin/login",
            data={"password": application.admin_password},
            follow_redirects=True,
        )

    def test_dashboard_requires_login_and_reports_daily_counts(self):
        self.assertEqual(self.client.get("/api/admin/month?month=2026-12").status_code, 401)
        self.login()

        booking_date = date.today() + timedelta(days=5)
        self.assertIsNotNone(
            application.reservation_store.create_reservation(
                "line-user", "測試訂位", 3, booking_date, "11:30"
            )
        )
        response = self.client.get(f"/api/admin/month?month={booking_date:%Y-%m}")
        self.assertEqual(response.status_code, 200)
        summary = response.json["daily"][booking_date.isoformat()]
        self.assertEqual(summary["count"], 1)
        self.assertEqual(summary["guests"], 3)

    def test_admin_cancel_requires_csrf_and_frees_reservation(self):
        self.login()
        booking = application.reservation_store.create_reservation(
            "line-user", "測試訂位", 2, date.today() + timedelta(days=5), "17:00"
        )
        self.assertEqual(
            self.client.post(f"/api/admin/reservations/{booking['id']}/cancel").status_code,
            403,
        )
        with self.client.session_transaction() as session:
            csrf_token = session["csrf_token"]
        response = self.client.post(
            f"/api/admin/reservations/{booking['id']}/cancel",
            headers={"X-CSRF-Token": csrf_token},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(application.reservation_store.get_reservation(booking["id"])["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
