"""
CLI runner for the Agentic Hospital Management System.

Usage::

    python -m HospitalManagement.run_demo
    python -m HospitalManagement.run_demo --patient P002 --query "Book a cardiologist"
    python -m HospitalManagement.run_demo --demo booking-fail
    python -m HospitalManagement.run_demo --demo notify-fail
    python -m HospitalManagement.run_demo --demo recovery
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from HospitalManagement.bootstrap import run_query
from HospitalManagement.core.hospital_db import HospitalDB


def _demo_standard() -> dict:
    """Standard assessment scenario."""
    return run_query(
        patient_id="P002",
        user_query=(
            "I have chest pain. "
            "Book the earliest appointment with a cardiologist. "
            "Check whether I already have an ECG report. "
            "If not, schedule an ECG test. "
            "Finally notify me with all the details."
        ),
    )


def _demo_recovery() -> dict:
    """
    Failure recovery demo: primary cardiologist has no slots,
    system should try alternate slots/doctors.
    """
    db = HospitalDB.from_seed()
    # Remove all slots from Dr. Brown to force fallback
    for doc in db.doctors:
        if doc["doctor_id"] == "D101":
            doc["available_slots"] = []

    # Add a second cardiologist with slots
    db.doctors.append({
        "doctor_id": "D201",
        "name": "Dr. White",
        "specialization": "Cardiology",
        "available_slots": ["2026-07-12 09:00", "2026-07-12 14:00"],
    })

    return run_query(
        patient_id="P002",
        user_query=(
            "I have chest pain. "
            "Book the earliest cardiologist appointment. "
            "Notify me when done."
        ),
        db=db,
    )


def _demo_booking_fail() -> dict:
    """
    Booking failure demo: no doctors available at all.
    """
    db = HospitalDB.from_seed()
    # Remove all cardiologist slots
    for doc in db.doctors:
        if doc["specialization"] == "Cardiology":
            doc["available_slots"] = []

    return run_query(
        patient_id="P002",
        user_query="Book a cardiologist appointment.",
        db=db,
    )


def _demo_notify_fail() -> dict:
    """
    Notification with everything working — demonstrates the
    multi-channel notification system.
    """
    return run_query(
        patient_id="P001",
        user_query=(
            "Check my existing lab reports and notify me of the results."
        ),
    )


DEMOS = {
    "standard": _demo_standard,
    "recovery": _demo_recovery,
    "booking-fail": _demo_booking_fail,
    "notify-fail": _demo_notify_fail,
}


def main():
    parser = argparse.ArgumentParser(
        description="Agentic Hospital Management System — CLI Demo"
    )
    parser.add_argument(
        "--patient", default=None, help="Patient ID (e.g. P002)"
    )
    parser.add_argument(
        "--query", default=None, help="Free-text patient request"
    )
    parser.add_argument(
        "--demo",
        choices=list(DEMOS.keys()),
        default=None,
        help="Run a pre-built demo scenario",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable debug logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s %(name)-30s %(levelname)-5s %(message)s",
        )
    else:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)-5s %(message)s",
        )

    # Run demo or custom query
    if args.demo:
        print(f"\n🏥 Running demo: {args.demo}")
        print("=" * 60)
        result = DEMOS[args.demo]()
    elif args.patient and args.query:
        print(f"\n🏥 Processing request for patient {args.patient}")
        print("=" * 60)
        result = run_query(patient_id=args.patient, user_query=args.query)
    else:
        print("\n🏥 Running default assessment scenario...")
        print("=" * 60)
        result = _demo_standard()

    # Pretty-print results
    print("\n📋 Final Output:")
    print("-" * 60)
    core_output = {
        "appointment_status": result.get("appointment_status"),
        "lab_test_status": result.get("lab_test_status"),
        "notification_status": result.get("notification_status"),
        "summary": result.get("summary"),
    }
    print(json.dumps(core_output, indent=2))

    # Task trace
    print("\n📊 Task Execution Trace:")
    print("-" * 60)
    for task in result.get("task_trace", []):
        status_icon = {
            "done": "✅",
            "failed": "❌",
            "skipped": "⏭️ ",
            "pending": "⏳",
            "running": "▶️ ",
        }.get(task["status"], "❓")
        duration = f" ({task['duration_ms']}ms)" if task.get("duration_ms") else ""
        print(f"  {status_icon} {task['kind']:<30} → {task['agent']}{duration}")
        if task.get("error"):
            print(f"     ↳ Error: {task['error']}")

    # Message trace
    print("\n💬 Agent Communication Log:")
    print("-" * 60)
    for msg in result.get("message_trace", []):
        print(f"  [{msg['sender']}] → [{msg['receiver']}]: {msg['content']}")

    print(f"\n⏱️  Total time: {result.get('elapsed_ms', '?')}ms")
    print(f"🔄 Retries: {result.get('retry_count', 0)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
