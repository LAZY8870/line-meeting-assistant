import json
import re
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from itertools import combinations

RESERVATION_MINUTES = 60
SLOT_INTERVAL_MINUTES = 60
MAX_ADVANCE_DAYS = 90
SLOT_WINDOWS = (("11:30", "14:30"), ("17:00", "20:00"))
TABLES = {
    **{f"2-{number}": 2 for number in range(1, 7)},
    **{f"4-{number}": 4 for number in range(1, 7)},
}


class ReservationStore:
    def __init__(self, database_path):
        self.database_path = database_path
        self.initialize()

    def connect(self):
        connection = sqlite3.connect(self.database_path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def initialize(self):
        with closing(self.connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS reservations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    line_user_id TEXT NOT NULL,
                    guest_name TEXT NOT NULL,
                    party_size INTEGER NOT NULL,
                    reservation_date TEXT NOT NULL,
                    reservation_time TEXT NOT NULL,
                    duration_minutes INTEGER NOT NULL,
                    table_ids TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'confirmed',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_reservations_date_status
                    ON reservations(reservation_date, status);
                CREATE TABLE IF NOT EXISTS conversation_states (
                    line_user_id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS processed_webhook_events (
                    event_id TEXT PRIMARY KEY,
                    processed_at TEXT NOT NULL
                );
                """
            )

    def claim_webhook_event(self, event_id):
        if not event_id:
            return True
        with closing(self.connect()) as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO processed_webhook_events(event_id, processed_at) VALUES (?, ?)",
                (event_id, datetime.now().isoformat(timespec="seconds")),
            )
            return cursor.rowcount == 1

    def get_state(self, user_id):
        with closing(self.connect()) as connection:
            row = connection.execute(
                "SELECT state_json FROM conversation_states WHERE line_user_id = ?",
                (user_id,),
            ).fetchone()
        return json.loads(row["state_json"]) if row else None

    def set_state(self, user_id, state):
        with closing(self.connect()) as connection:
            connection.execute(
                """
                INSERT INTO conversation_states(line_user_id, state_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(line_user_id) DO UPDATE SET
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (user_id, json.dumps(state, ensure_ascii=False), datetime.now().isoformat(timespec="seconds")),
            )

    def clear_state(self, user_id):
        with closing(self.connect()) as connection:
            connection.execute("DELETE FROM conversation_states WHERE line_user_id = ?", (user_id,))

    @staticmethod
    def _minutes(time_text):
        hour, minute = (int(part) for part in time_text.split(":"))
        return hour * 60 + minute

    def get_slots(self, reservation_date, party_size):
        if not 1 <= party_size <= sum(TABLES.values()):
            return []
        slots = []
        for start_text, end_text in SLOT_WINDOWS:
            start = self._minutes(start_text)
            end = self._minutes(end_text)
            while start + RESERVATION_MINUTES <= end:
                time_text = f"{start // 60:02d}:{start % 60:02d}"
                if self._is_future(reservation_date, time_text) and self.available_tables(
                    reservation_date, time_text, party_size
                ):
                    slots.append(time_text)
                start += SLOT_INTERVAL_MINUTES
        return slots

    @classmethod
    def is_opening_slot(cls, reservation_time):
        for window_start, window_end in SLOT_WINDOWS:
            start = cls._minutes(window_start)
            end = cls._minutes(window_end)
            while start + RESERVATION_MINUTES <= end:
                if reservation_time == f"{start // 60:02d}:{start % 60:02d}":
                    return True
                start += SLOT_INTERVAL_MINUTES
        return False

    @staticmethod
    def _is_future(reservation_date, time_text):
        today = date.today()
        if reservation_date < today:
            return False
        if reservation_date == today:
            start_at = datetime.combine(today, datetime.strptime(time_text, "%H:%M").time())
            return start_at > datetime.now()
        return True

    def _available_tables(self, connection, reservation_date, reservation_time, party_size):
        if party_size < 1 or party_size > sum(TABLES.values()):
            return []
        start = self._minutes(reservation_time)
        end = start + RESERVATION_MINUTES
        occupied = set()
        rows = connection.execute(
            """
            SELECT reservation_time, duration_minutes, table_ids
            FROM reservations
            WHERE reservation_date = ? AND status = 'confirmed'
            """,
            (reservation_date.isoformat(),),
        ).fetchall()
        for row in rows:
            other_start = self._minutes(row["reservation_time"])
            other_end = other_start + row["duration_minutes"]
            if start < other_end and end > other_start:
                occupied.update(json.loads(row["table_ids"]))

        free_tables = [table_id for table_id in TABLES if table_id not in occupied]
        candidates = []
        for count in range(1, len(free_tables) + 1):
            for group in combinations(free_tables, count):
                capacity = sum(TABLES[table_id] for table_id in group)
                if capacity >= party_size:
                    candidates.append((count, capacity - party_size, group))
            if candidates:
                break
        if not candidates:
            return []
        return list(min(candidates, key=lambda item: (item[0], item[1], item[2]))[2])

    def available_tables(self, reservation_date, reservation_time, party_size):
        with closing(self.connect()) as connection:
            return self._available_tables(connection, reservation_date, reservation_time, party_size)

    def create_reservation(self, user_id, guest_name, party_size, reservation_date, reservation_time):
        if (
            reservation_date is None
            or not self.is_opening_slot(reservation_time)
            or not self._is_future(reservation_date, reservation_time)
        ):
            return None
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            tables = self._available_tables(connection, reservation_date, reservation_time, party_size)
            if not tables:
                connection.rollback()
                return None
            cursor = connection.execute(
                """
                INSERT INTO reservations(
                    line_user_id, guest_name, party_size, reservation_date,
                    reservation_time, duration_minutes, table_ids, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    guest_name,
                    party_size,
                    reservation_date.isoformat(),
                    reservation_time,
                    RESERVATION_MINUTES,
                    json.dumps(tables),
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            reservation_id = cursor.lastrowid
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return self.get_reservation(reservation_id)

    def get_reservation(self, reservation_id):
        with closing(self.connect()) as connection:
            row = connection.execute("SELECT * FROM reservations WHERE id = ?", (reservation_id,)).fetchone()
        return self._serialize(row) if row else None

    def get_user_reservations(self, user_id):
        today = date.today().isoformat()
        current_time = datetime.now().strftime("%H:%M")
        with closing(self.connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM reservations
                WHERE line_user_id = ? AND status = 'confirmed'
                    AND (reservation_date > ? OR (reservation_date = ? AND reservation_time > ?))
                ORDER BY reservation_date, reservation_time
                """,
                (user_id, today, today, current_time),
            ).fetchall()
        return [self._serialize(row) for row in rows]

    def cancel_user_reservation(self, reservation_id, user_id):
        today = date.today().isoformat()
        current_time = datetime.now().strftime("%H:%M")
        with closing(self.connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE reservations SET status = 'cancelled'
                WHERE id = ? AND line_user_id = ? AND status = 'confirmed'
                    AND (reservation_date > ? OR (reservation_date = ? AND reservation_time > ?))
                """,
                (reservation_id, user_id, today, today, current_time),
            )
            return cursor.rowcount == 1

    def cancel_admin_reservation(self, reservation_id):
        with closing(self.connect()) as connection:
            cursor = connection.execute(
                "UPDATE reservations SET status = 'cancelled' WHERE id = ? AND status = 'confirmed'",
                (reservation_id,),
            )
            return cursor.rowcount == 1

    @staticmethod
    def _serialize(row):
        item = dict(row)
        item["table_ids"] = json.loads(item["table_ids"])
        return item

    def get_month(self, year, month):
        first_day = date(year, month, 1)
        last_day = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
        with closing(self.connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM reservations
                WHERE reservation_date >= ? AND reservation_date <= ?
                ORDER BY reservation_date, reservation_time, id
                """,
                (first_day.isoformat(), last_day.isoformat()),
            ).fetchall()
        reservations = [self._serialize(row) for row in rows]
        daily = {}
        for item in reservations:
            summary = daily.setdefault(item["reservation_date"], {"count": 0, "guests": 0, "reservations": []})
            if item["status"] == "confirmed":
                summary["count"] += 1
                summary["guests"] += item["party_size"]
            summary["reservations"].append(item)
        return {
            "month": first_day.strftime("%Y-%m"),
            "daily": daily,
            "reservations": reservations,
        }


def parse_reservation_date(text):
    normalized = text.strip().replace("／", "/").replace("年", "/").replace("月", "/").replace("日", "")
    today = date.today()
    if normalized in ("今天", "今日"):
        parsed = today
    elif normalized == "明天":
        parsed = today + timedelta(days=1)
    elif normalized == "後天":
        parsed = today + timedelta(days=2)
    else:
        normalized = normalized.replace(".", "/").replace("-", "/")
        match = re.fullmatch(r"(\d{4})/(\d{1,2})/(\d{1,2})", normalized)
        if not match:
            return None
        try:
            parsed = date(*(int(part) for part in match.groups()))
        except ValueError:
            return None
    if parsed < today or parsed > today + timedelta(days=MAX_ADVANCE_DAYS):
        return None
    return parsed


def normalize_reservation_time(text):
    normalized = text.strip().replace("：", ":").replace("點", ":").replace("時", ":").replace("分", "")
    match = re.fullmatch(r"(\d{1,2}):?(\d{2})", normalized)
    if not match:
        return None
    hour, minute = (int(part) for part in match.groups())
    if hour > 23 or minute > 59:
        return None
    time_text = f"{hour:02d}:{minute:02d}"
    for window_start, window_end in SLOT_WINDOWS:
        start = ReservationStore._minutes(window_start)
        end = ReservationStore._minutes(window_end)
        while start + RESERVATION_MINUTES <= end:
            if time_text == f"{start // 60:02d}:{start % 60:02d}":
                return time_text
            start += SLOT_INTERVAL_MINUTES
    return None
