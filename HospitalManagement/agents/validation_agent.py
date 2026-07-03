"""
Validation Agent — Requirement 6: Validation and Self-Correction.

Runs after all other agents complete.  Verifies:
1. Every requested task has been completed.
2. No unnecessary actions were performed.
3. No hallucinated information is present.
4. The final response matches tool outputs.

If inconsistencies are detected, signals the orchestrator to retry.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from HospitalManagement.agents.base import BaseAgent
from HospitalManagement.core.state import SharedState, Task, TaskStatus

logger = logging.getLogger(__name__)


class ValidationAgent(BaseAgent):
    """
    Cross-checks every output field against actual tool results.

    Returns a validation report.  If ``issues`` is non-empty,
    the orchestrator may trigger a retry cycle.
    """

    name = "ValidationAgent"

    def execute(self, task: Task, state: SharedState) -> Any:
        issues: List[str] = []
        nlu = state.metadata.get("nlu")

        if not nlu:
            issues.append("NLU result missing — cannot validate intents")
            return self._finalize(state, issues)

        # ── 1. Check booking completion ──────────────────────────
        if nlu.wants_booking:
            appt_status = state.output.get("appointment_status", "")
            book_task = state.get_task_by_kind("BOOK_APPOINTMENT")

            if book_task and book_task.status == TaskStatus.DONE:
                # Verify the appointment actually exists in DB
                booked = state.metadata.get("booked_appointment")
                if booked:
                    appt_id = booked["appointment_id"]
                    db_appts = state.db.conn.execute(
                        "SELECT * FROM appointments WHERE appointment_id = ?", (appt_id,)
                    ).fetchall()
                    if not db_appts:
                        issues.append(
                            f"Hallucination: appointment {appt_id} "
                            f"not found in database"
                        )
                elif not appt_status:
                    issues.append(
                        "Booking task DONE but no appointment record in metadata"
                    )
            elif book_task and book_task.status == TaskStatus.FAILED:
                # Acceptable — failure was recorded
                if "Failed" not in appt_status:
                    issues.append(
                        "Booking failed but appointment_status doesn't "
                        "reflect failure"
                    )
            elif book_task and book_task.status == TaskStatus.SKIPPED:
                # Upstream failure cascaded — ensure status reflects it
                if not appt_status:
                    search_task = state.get_task_by_kind("SEARCH_DOCTORS")
                    if search_task and search_task.error:
                        state.output["appointment_status"] = (
                            f"Failed - {search_task.error}"
                        )
                    else:
                        state.output["appointment_status"] = (
                            "Failed - upstream dependency failed"
                        )

        # ── 2. Check lab test completion ─────────────────────────
        for test in nlu.lab_tests_to_check:
            kind = f"CHECK_LAB_{test.upper().replace(' ', '_')}"
            lab_task = state.get_task_by_kind(kind)
            if lab_task:
                if lab_task.status == TaskStatus.DONE:
                    # Verify: if scheduled, check DB has it
                    result = lab_task.result
                    if isinstance(result, dict) and result.get("action") == "scheduled":
                        lab_id = result.get("lab_id")
                        db_labs = state.db.conn.execute(
                            "SELECT * FROM lab_reports WHERE lab_id = ?", (lab_id,)
                        ).fetchall()
                        if not db_labs:
                            issues.append(
                                f"Hallucination: lab test {lab_id} "
                                f"not found in database"
                            )
                elif lab_task.status == TaskStatus.FAILED:
                    if "lab_test_status" not in state.output:
                        issues.append(
                            f"Lab check for '{test}' failed but "
                            f"lab_test_status not set"
                        )

        # ── 3. Check notification completion ─────────────────────
        if nlu.wants_notification:
            notify_task = state.get_task_by_kind("SEND_NOTIFICATION")
            if notify_task:
                if notify_task.status == TaskStatus.DONE:
                    if "notification_status" not in state.output:
                        issues.append(
                            "Notification sent but notification_status not set"
                        )
                elif notify_task.status == TaskStatus.FAILED:
                    if "notification_status" not in state.output:
                        state.output["notification_status"] = (
                            f"Failed - {notify_task.error}"
                        )
                elif notify_task.status == TaskStatus.SKIPPED:
                    state.output["notification_status"] = (
                        "Skipped - dependent tasks failed"
                    )

        # ── 4. Check for unnecessary actions ─────────────────────
        if not nlu.wants_booking:
            book_task = state.get_task_by_kind("BOOK_APPOINTMENT")
            if book_task and book_task.status == TaskStatus.DONE:
                issues.append(
                    "Unnecessary booking performed — patient did not request it"
                )

        return self._finalize(state, issues)

    def _finalize(
        self, state: SharedState, issues: List[str]
    ) -> Dict[str, Any]:
        """Build the final summary and return the validation report."""
        # Build summary
        summary_parts = []
        nlu = state.metadata.get("nlu")

        patient = state.metadata.get("patient", {})
        if patient:
            summary_parts.append(
                f"Patient: {patient.get('name', state.patient_id)}"
            )

        if nlu and nlu.symptoms:
            summary_parts.append(f"Symptoms: {', '.join(nlu.symptoms)}")

        appt_status = state.output.get("appointment_status", "N/A")
        summary_parts.append(f"Appointment: {appt_status}")

        lab_status = state.output.get("lab_test_status", "N/A")
        summary_parts.append(f"Lab Test: {lab_status}")

        notif_status = state.output.get("notification_status", "N/A")
        summary_parts.append(f"Notification: {notif_status}")

        state.output["summary"] = ". ".join(summary_parts) + "."

        # Post validation message
        if issues:
            state.post_message(
                sender=self.name,
                receiver="Orchestrator",
                content=f"Validation found {len(issues)} issue(s)",
                data={"issues": issues},
            )
            logger.warning("Validation issues: %s", issues)
        else:
            state.post_message(
                sender=self.name,
                receiver="*",
                content="Validation passed — all checks OK",
            )

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "output": dict(state.output),
        }
