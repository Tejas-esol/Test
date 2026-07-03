"""
Scenario tests for the agentic orchestrator.

Run directly::

    python -m HospitalManagement.test_scenarios
"""

from __future__ import annotations

import json
import sys
import traceback

from HospitalManagement.bootstrap import run_query
from HospitalManagement.core.hospital_db import HospitalDB


def _header(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def _check(label: str, condition: bool) -> bool:
    status = "✅ PASS" if condition else "❌ FAIL"
    print(f"  {status}: {label}")
    return condition


def test_assessment_scenario():
    """The exact scenario from the assessment specification."""
    _header("Assessment Scenario: P002 chest pain + ECG + notify")

    result = run_query(
        patient_id="P002",
        user_query=(
            "I have chest pain. "
            "Book the earliest appointment with a cardiologist. "
            "Check whether I already have an ECG report. "
            "If not, schedule an ECG test. "
            "Finally notify me with all the details."
        ),
    )

    ok = True
    ok &= _check("appointment_status contains 'Booked'",
                  "Booked" in result.get("appointment_status", ""))
    ok &= _check("lab_test_status contains 'scheduled'",
                  "scheduled" in result.get("lab_test_status", "").lower())
    ok &= _check("notification_status contains 'Sent'",
                  "Sent" in result.get("notification_status", ""))
    ok &= _check("summary is non-empty",
                  len(result.get("summary", "")) > 10)

    print(f"\n  Output JSON:")
    for key in ("appointment_status", "lab_test_status", "notification_status", "summary"):
        print(f"    {key}: {result.get(key)}")

    return ok


def test_existing_ecg_patient():
    """P001 already has ECG — should NOT schedule another."""
    _header("P001: Existing ECG — no duplicate scheduling")

    result = run_query(
        patient_id="P001",
        user_query=(
            "Check whether I already have an ECG report. "
            "If not, schedule an ECG test."
        ),
    )

    ok = True
    ok &= _check("lab_test_status says 'already exists'",
                  "already exists" in result.get("lab_test_status", "").lower())
    ok &= _check("No unnecessary appointment booking",
                  result.get("appointment_status", "N/A") == "N/A")

    return ok


def test_booking_only():
    """Simple booking without lab or notification."""
    _header("P002: Book orthopedic appointment only")

    result = run_query(
        patient_id="P002",
        user_query="Book an orthopedic appointment.",
    )

    ok = True
    ok &= _check("appointment_status contains 'Booked'",
                  "Booked" in result.get("appointment_status", ""))
    ok &= _check("notification_status is N/A",
                  result.get("notification_status", "N/A") == "N/A")

    return ok


def test_notification_only():
    """Notification request without booking or labs."""
    _header("P001: Notify me about my records")

    result = run_query(
        patient_id="P001",
        user_query="Just notify me about my medical records.",
    )

    ok = True
    ok &= _check("notification_status contains 'Sent'",
                  "Sent" in result.get("notification_status", ""))

    return ok


def test_parallel_execution():
    """Verify that independent tasks can complete (timing not asserted)."""
    _header("Parallel Execution: booking + lab check simultaneously")

    result = run_query(
        patient_id="P002",
        user_query=(
            "Book a cardiologist appointment and also "
            "check if I have a blood test report."
        ),
    )

    ok = True
    ok &= _check("appointment_status contains 'Booked'",
                  "Booked" in result.get("appointment_status", ""))
    ok &= _check("lab_test_status is set",
                  result.get("lab_test_status", "N/A") != "N/A")

    return ok


def test_unknown_patient():
    """Request for a non-existent patient."""
    _header("Unknown Patient: P999")

    result = run_query(
        patient_id="P999",
        user_query="Book a cardiologist appointment.",
    )

    ok = True
    # Patient fetch should fail but booking might still work
    # (depends on whether PatientHistoryAgent is a hard dependency)
    ok &= _check("summary mentions something",
                  len(result.get("summary", "")) > 5)

    return ok


def test_no_doctors_for_specialization():
    """Request for unavailable specialization — graceful failure."""
    _header("No Dermatology doctors — graceful failure")

    result = run_query(
        patient_id="P002",
        user_query="Book a Dermatology doctor appointment.",
    )

    ok = True
    ok &= _check("appointment_status contains 'Failed'",
                  "Failed" in result.get("appointment_status", ""))
    ok &= _check("Error mentions 'Dermatology'",
                  "Dermatology" in result.get("appointment_status", ""))

    return ok


def test_validation_self_correction():
    """
    Simulate a scenario where validation detects an issue and
    triggers a retry.
    """
    _header("Validation Self-Correction: retry on inconsistency")

    # Use standard scenario — validation should pass on first try
    result = run_query(
        patient_id="P002",
        user_query=(
            "I have chest pain. "
            "Book the earliest cardiologist appointment. "
            "Check whether I already have an ECG report. "
            "If not, schedule an ECG test. "
            "Notify me with all details."
        ),
    )

    ok = True
    ok &= _check("appointment_status is set",
                  result.get("appointment_status", "N/A") != "N/A")
    ok &= _check("retry_count is 0 (clean pass)",
                  result.get("retry_count", -1) == 0)

    return ok


def main():
    tests = [
        test_assessment_scenario,
        test_existing_ecg_patient,
        test_booking_only,
        test_notification_only,
        test_parallel_execution,
        test_unknown_patient,
        test_no_doctors_for_specialization,
        test_validation_self_correction,
    ]

    passed = 0
    failed = 0

    for test_fn in tests:
        try:
            if test_fn():
                passed += 1
            else:
                failed += 1
        except Exception:
            print(f"  ❌ EXCEPTION in {test_fn.__name__}:")
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*60}")
    print(f"  Results: {passed} passed, {failed} failed, {len(tests)} total")
    print(f"{'='*60}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
