"""
Hospital Database — SQLite-backed persistent store.

Replaces the in-memory dict-based storage with a real SQLite
database.  Schema supports patients, doctors, slots, appointments,
lab reports, and notifications.

Key design decisions:
- Uses SQLite WAL mode for concurrent read access.
- ``from_seed()`` connects to a persistent file and seeds if empty.
- ``from_memory()`` creates an ephemeral in-memory DB for testing.
- Same public interface as the original dict-based HospitalDB so
  all agents work without modification.
- Future-ready: new patients, doctors, and reports persist across
  restarts and can be queried by the agentic workflow.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional


# ──────────────────────────────────────────────────────────────────
# Default DB path (in the project directory)
# ──────────────────────────────────────────────────────────────────

_DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "hospital_data.db",
)


# ──────────────────────────────────────────────────────────────────
# Schema
# ──────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
    patient_id   TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    age          INTEGER,
    email        TEXT,
    phone        TEXT,
    created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS doctors (
    doctor_id       TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    specialization  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS doctor_slots (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor_id  TEXT NOT NULL REFERENCES doctors(doctor_id),
    slot_time  TEXT NOT NULL,
    is_booked  INTEGER DEFAULT 0,
    UNIQUE(doctor_id, slot_time)
);

CREATE TABLE IF NOT EXISTS appointments (
    appointment_id  TEXT PRIMARY KEY,
    patient_id      TEXT NOT NULL REFERENCES patients(patient_id),
    doctor_id       TEXT NOT NULL REFERENCES doctors(doctor_id),
    slot_time       TEXT NOT NULL,
    status          TEXT DEFAULT 'Confirmed',
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS lab_reports (
    lab_id        TEXT PRIMARY KEY,
    patient_id    TEXT NOT NULL REFERENCES patients(patient_id),
    test_name     TEXT NOT NULL,
    status        TEXT DEFAULT 'Scheduled',
    scheduled_at  TEXT,
    completed_at  TEXT
);

CREATE TABLE IF NOT EXISTS notifications (
    notification_id  TEXT PRIMARY KEY,
    patient_id       TEXT NOT NULL REFERENCES patients(patient_id),
    channel          TEXT NOT NULL,
    message          TEXT NOT NULL,
    status           TEXT DEFAULT 'Sent',
    sent_at          TEXT DEFAULT (datetime('now'))
);
"""


# ──────────────────────────────────────────────────────────────────
# Seed data (matches assessment specification)
# ──────────────────────────────────────────────────────────────────

_SEED_PATIENTS = [
    ("P001", "John Doe", 45, "johndoe@email.com", "+1-555-0101"),
    ("P002", "Alice Smith", 32, "alice.smith@email.com", "+1-555-0102"),
]

_SEED_DOCTORS = [
    ("D101", "Dr. Brown", "Cardiology"),
    ("D102", "Dr. Green", "Orthopedics"),
]

_SEED_SLOTS = [
    ("D101", "2026-07-10 09:00"),
    ("D101", "2026-07-10 11:00"),
    ("D102", "2026-07-11 10:00"),
    ("D102", "2026-07-11 14:00"),
]

_SEED_APPOINTMENTS = [
    ("A101", "P001", "D101", "2026-07-10 09:00", "Confirmed"),
]

_SEED_LAB_REPORTS = [
    ("L001", "P001", "ECG", "Completed", "2026-07-01T10:00:00", "2026-07-02T14:00:00"),
    ("L002", "P001", "Blood Test", "Completed", "2026-07-01T10:00:00", "2026-07-02T16:00:00"),
]


# ──────────────────────────────────────────────────────────────────
# Row factory
# ──────────────────────────────────────────────────────────────────

def _dict_factory(cursor, row):
    """Convert SQLite rows to dicts automatically."""
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


# ──────────────────────────────────────────────────────────────────
# HospitalDB — SQLite-backed persistent store
# ──────────────────────────────────────────────────────────────────

class HospitalDB:
    """
    SQLite-backed hospital data store.

    Provides the same public interface as the original in-memory
    version so all agents work without modification.

    Thread-safe via ``check_same_thread=False`` + SQLite WAL mode.
    Write operations use a threading lock for safety.
    """

    def __init__(self, db_path: str = _DEFAULT_DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = _dict_factory
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        """Create tables if they don't exist."""
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def _is_empty(self) -> bool:
        """Check if the database has any patient records."""
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM patients"
        ).fetchone()
        return row["cnt"] == 0

    # ── factory methods ──────────────────────────────────────────

    @classmethod
    def from_seed(
        cls,
        db_path: str = _DEFAULT_DB_PATH,
        **kwargs,
    ) -> "HospitalDB":
        """
        Connect to a persistent SQLite database.
        Creates tables and seeds initial data if the DB is empty.
        """
        db = cls(db_path=db_path)
        if db._is_empty():
            db._seed_data()
        return db

    @classmethod
    def from_memory(cls) -> "HospitalDB":
        """
        Create an ephemeral in-memory SQLite database with seed data.
        Useful for testing — each call returns a fresh, isolated DB.
        """
        return cls.from_seed(db_path=":memory:")

    # ── seed data ────────────────────────────────────────────────

    def _seed_data(self) -> None:
        """Populate the database with initial sample data."""
        with self._lock:
            self.conn.executemany(
                "INSERT OR IGNORE INTO patients (patient_id, name, age, email, phone) VALUES (?, ?, ?, ?, ?)",
                _SEED_PATIENTS,
            )
            self.conn.executemany(
                "INSERT OR IGNORE INTO doctors (doctor_id, name, specialization) VALUES (?, ?, ?)",
                _SEED_DOCTORS,
            )
            self.conn.executemany(
                "INSERT OR IGNORE INTO doctor_slots (doctor_id, slot_time) VALUES (?, ?)",
                _SEED_SLOTS,
            )
            # Mark A101's slot as booked (P001 already has this appointment)
            self.conn.execute(
                "UPDATE doctor_slots SET is_booked = 1 WHERE doctor_id = 'D101' AND slot_time = '2026-07-10 09:00'"
            )
            self.conn.executemany(
                "INSERT OR IGNORE INTO appointments (appointment_id, patient_id, doctor_id, slot_time, status) "
                "VALUES (?, ?, ?, ?, ?)",
                _SEED_APPOINTMENTS,
            )
            self.conn.executemany(
                "INSERT OR IGNORE INTO lab_reports (lab_id, patient_id, test_name, status, scheduled_at, completed_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                _SEED_LAB_REPORTS,
            )
            self.conn.commit()

    def reset(self) -> None:
        """Drop all data and re-seed.  Used for demo / testing."""
        with self._lock:
            self.conn.executescript("""
                DELETE FROM notifications;
                DELETE FROM lab_reports;
                DELETE FROM appointments;
                DELETE FROM doctor_slots;
                DELETE FROM doctors;
                DELETE FROM patients;
            """)
            self.conn.commit()
        self._seed_data()

    # ── patient queries ──────────────────────────────────────────

    def get_patient(self, patient_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a patient record with their appointments and lab reports."""
        row = self.conn.execute(
            "SELECT * FROM patients WHERE patient_id = ?", (patient_id,)
        ).fetchone()
        if row is None:
            return None

        patient = dict(row)

        # Attach appointment IDs
        appts = self.conn.execute(
            "SELECT appointment_id FROM appointments WHERE patient_id = ?",
            (patient_id,),
        ).fetchall()
        patient["appointments"] = [a["appointment_id"] for a in appts]

        # Attach lab report test names
        labs = self.conn.execute(
            "SELECT DISTINCT test_name FROM lab_reports WHERE patient_id = ?",
            (patient_id,),
        ).fetchall()
        patient["lab_reports"] = [l["test_name"] for l in labs]

        return patient

    def get_all_patients(self) -> List[Dict[str, Any]]:
        """Return all patients with their details."""
        rows = self.conn.execute(
            "SELECT patient_id FROM patients ORDER BY patient_id"
        ).fetchall()
        return [self.get_patient(r["patient_id"]) for r in rows]

    # ── doctor queries ───────────────────────────────────────────

    def all_specializations(self) -> List[str]:
        """Return sorted list of unique specializations."""
        rows = self.conn.execute(
            "SELECT DISTINCT specialization FROM doctors ORDER BY specialization"
        ).fetchall()
        return [r["specialization"] for r in rows]

    def find_doctors(
        self, specialization: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Return doctors optionally filtered by specialization."""
        if specialization:
            rows = self.conn.execute(
                "SELECT * FROM doctors WHERE specialization = ? COLLATE NOCASE",
                (specialization,),
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM doctors").fetchall()

        result = []
        for row in rows:
            doc = dict(row)
            slots = self.conn.execute(
                "SELECT slot_time FROM doctor_slots "
                "WHERE doctor_id = ? AND is_booked = 0 ORDER BY slot_time",
                (doc["doctor_id"],),
            ).fetchall()
            doc["available_slots"] = [s["slot_time"] for s in slots]
            result.append(doc)
        return result

    def get_doctor(self, doctor_id: str) -> Optional[Dict[str, Any]]:
        """Get a single doctor with available slots."""
        row = self.conn.execute(
            "SELECT * FROM doctors WHERE doctor_id = ?", (doctor_id,)
        ).fetchone()
        if row is None:
            return None
        doc = dict(row)
        slots = self.conn.execute(
            "SELECT slot_time FROM doctor_slots "
            "WHERE doctor_id = ? AND is_booked = 0 ORDER BY slot_time",
            (doctor_id,),
        ).fetchall()
        doc["available_slots"] = [s["slot_time"] for s in slots]
        return doc

    def get_all_doctors(self) -> List[Dict[str, Any]]:
        """Return all doctors with their available slots."""
        return self.find_doctors()

    # ── slot management ──────────────────────────────────────────

    def available_slots(self, doctor_id: str) -> List[str]:
        """Get available (unbooked) slots for a doctor."""
        rows = self.conn.execute(
            "SELECT slot_time FROM doctor_slots "
            "WHERE doctor_id = ? AND is_booked = 0 ORDER BY slot_time",
            (doctor_id,),
        ).fetchall()
        return [r["slot_time"] for r in rows]

    def _consume_slot(self, doctor_id: str, slot: str) -> bool:
        """Mark a slot as booked.  Returns True on success."""
        with self._lock:
            cursor = self.conn.execute(
                "UPDATE doctor_slots SET is_booked = 1 "
                "WHERE doctor_id = ? AND slot_time = ? AND is_booked = 0",
                (doctor_id, slot),
            )
            self.conn.commit()
            return cursor.rowcount > 0

    # ── appointment booking ──────────────────────────────────────

    def book_appointment(
        self,
        patient_id: str,
        doctor_id: str,
        slot: str,
    ) -> Dict[str, Any]:
        """
        Book an appointment.  Raises ``ValueError`` if slot unavailable.
        """
        if not self._consume_slot(doctor_id, slot):
            raise ValueError(
                f"Slot '{slot}' is not available for doctor '{doctor_id}'"
            )

        appt_id = self._next_appt_id()
        now = datetime.now().isoformat(timespec="seconds")

        with self._lock:
            self.conn.execute(
                "INSERT INTO appointments (appointment_id, patient_id, doctor_id, slot_time, status, created_at) "
                "VALUES (?, ?, ?, ?, 'Confirmed', ?)",
                (appt_id, patient_id, doctor_id, slot, now),
            )
            self.conn.commit()

        return {
            "appointment_id": appt_id,
            "patient_id": patient_id,
            "doctor_id": doctor_id,
            "slot": slot,
        }

    def _next_appt_id(self) -> str:
        """Generate the next sequential appointment ID."""
        row = self.conn.execute(
            "SELECT appointment_id FROM appointments ORDER BY appointment_id DESC LIMIT 1"
        ).fetchone()
        if row:
            try:
                num = int(row["appointment_id"].replace("A", "")) + 1
            except ValueError:
                num = 200
        else:
            num = 200
        return f"A{num}"

    # ── lab report queries ───────────────────────────────────────

    def get_lab_reports(self, patient_id: str) -> List[Dict[str, Any]]:
        """Get all lab reports for a patient."""
        return self.conn.execute(
            "SELECT * FROM lab_reports WHERE patient_id = ? ORDER BY test_name",
            (patient_id,),
        ).fetchall()

    def has_lab_report(self, patient_id: str, test_name: str) -> bool:
        """Check if a patient has a specific lab report."""
        row = self.conn.execute(
            "SELECT 1 FROM lab_reports WHERE patient_id = ? AND test_name = ? COLLATE NOCASE LIMIT 1",
            (patient_id, test_name),
        ).fetchone()
        return row is not None

    # ── lab test scheduling ──────────────────────────────────────

    def schedule_lab_test(
        self,
        patient_id: str,
        test_name: str,
    ) -> Dict[str, Any]:
        """Schedule a new lab test.  Returns the created record."""
        lab_id = self._next_lab_id()
        now = datetime.now().isoformat(timespec="seconds")

        with self._lock:
            self.conn.execute(
                "INSERT INTO lab_reports (lab_id, patient_id, test_name, status, scheduled_at) "
                "VALUES (?, ?, ?, 'Scheduled', ?)",
                (lab_id, patient_id, test_name, now),
            )
            self.conn.commit()

        return {
            "lab_id": lab_id,
            "patient_id": patient_id,
            "test_name": test_name,
            "status": "Scheduled",
            "scheduled_at": now,
        }

    def _next_lab_id(self) -> str:
        """Generate the next sequential lab ID."""
        row = self.conn.execute(
            "SELECT lab_id FROM lab_reports WHERE lab_id LIKE 'L%' ORDER BY lab_id DESC LIMIT 1"
        ).fetchone()
        if row:
            try:
                num = int(row["lab_id"].replace("L", "")) + 1
            except ValueError:
                num = 500
        else:
            num = 500
        return f"L{num}"

    # ── notifications ────────────────────────────────────────────

    def send_notification(
        self,
        patient_id: str,
        channel: str,
        message: str,
    ) -> Dict[str, Any]:
        """Record a notification sent to a patient."""
        notif_id = f"N-{uuid.uuid4().hex[:8]}"
        now = datetime.now().isoformat(timespec="seconds")

        with self._lock:
            self.conn.execute(
                "INSERT INTO notifications (notification_id, patient_id, channel, message, status, sent_at) "
                "VALUES (?, ?, ?, ?, 'Sent', ?)",
                (notif_id, patient_id, channel, message, now),
            )
            self.conn.commit()

        return {
            "notification_id": notif_id,
            "patient_id": patient_id,
            "channel": channel,
            "message": message,
            "sent_at": now,
            "status": "Sent",
        }

    # ── admin / utility ──────────────────────────────────────────

    def add_patient(
        self,
        patient_id: str,
        name: str,
        age: int,
        email: str = "",
        phone: str = "",
    ) -> Dict[str, Any]:
        """Add a new patient to the database."""
        with self._lock:
            self.conn.execute(
                "INSERT INTO patients (patient_id, name, age, email, phone) VALUES (?, ?, ?, ?, ?)",
                (patient_id, name, age, email, phone),
            )
            self.conn.commit()
        return self.get_patient(patient_id)

    def add_doctor(
        self,
        doctor_id: str,
        name: str,
        specialization: str,
        slots: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Add a new doctor with optional available slots."""
        with self._lock:
            self.conn.execute(
                "INSERT INTO doctors (doctor_id, name, specialization) VALUES (?, ?, ?)",
                (doctor_id, name, specialization),
            )
            if slots:
                self.conn.executemany(
                    "INSERT INTO doctor_slots (doctor_id, slot_time) VALUES (?, ?)",
                    [(doctor_id, s) for s in slots],
                )
            self.conn.commit()
        return self.get_doctor(doctor_id)

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()
